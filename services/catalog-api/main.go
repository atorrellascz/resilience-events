package main

import (
	"context"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"strconv"
	"time"

	"github.com/atorrellascz/resilience-events/catalog-api/handler"
	"github.com/atorrellascz/resilience-events/catalog-api/repository"
	"github.com/atorrellascz/resilience-events/catalog-api/service"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

// ── Métricas RED, con los MISMOS nombres que prometheus-net (.NET) ──
// Así el dashboard funciona igual para todos los servicios polyglot.
var (
	httpRequestsTotal = prometheus.NewCounterVec(
		prometheus.CounterOpts{
			Name: "http_requests_received_total",
			Help: "Total HTTP requests received.",
		},
		[]string{"code", "method", "endpoint"},
	)
	httpRequestDuration = prometheus.NewHistogramVec(
		prometheus.HistogramOpts{
			Name:    "http_request_duration_seconds",
			Help:    "HTTP request duration in seconds.",
			Buckets: prometheus.DefBuckets, // 0.005 .. 10s
		},
		[]string{"code", "method", "endpoint"},
	)
)

func init() {
	// Registramos las métricas en el registro por defecto de Prometheus.
	prometheus.MustRegister(httpRequestsTotal, httpRequestDuration)
}

func main() {
	mongoURI := getEnv("MONGO_URI", "mongodb://mongodb:27017")
	dbName := getEnv("MONGO_DB", "catalog")

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	repo, err := repository.NewMongoRepository(ctx, mongoURI, dbName)
	if err != nil {
		log.Fatalf("failed to connect to MongoDB: %v", err)
	}
	log.Printf("connected to MongoDB at %s (db=%s)", mongoURI, dbName)

	svc := service.NewCatalogService(repo)
	h := handler.NewCatalogHandler(svc)

	mux := http.NewServeMux()
	h.Register(mux)

	mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "healthy"})
	})

	mux.HandleFunc("GET /ready", func(w http.ResponseWriter, r *http.Request) {
		if err := svc.Ready(r.Context()); err != nil {
			writeJSON(w, http.StatusServiceUnavailable,
				map[string]string{"status": "not-ready", "reason": "database unreachable"})
			return
		}
		writeJSON(w, http.StatusOK, map[string]string{"status": "ready"})
	})

	// El handler oficial de Prometheus expone TODAS las métricas registradas.
	mux.Handle("GET /metrics", promhttp.Handler())

	// Middleware que mide cada request (rate, errores, duración).
	wrapped := metricsMiddleware(mux)

	addr := ":8080"
	log.Printf("catalog-api listening on %s", addr)
	log.Fatal(http.ListenAndServe(addr, wrapped))
}

// statusRecorder captura el código de estado para poder etiquetarlo.
type statusRecorder struct {
	http.ResponseWriter
	status int
}

func (r *statusRecorder) WriteHeader(code int) {
	r.status = code
	r.ResponseWriter.WriteHeader(code)
}

// metricsMiddleware registra rate + errores + duración por cada request.
func metricsMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// No medimos /metrics a sí mismo (ruido).
		if r.URL.Path == "/metrics" {
			next.ServeHTTP(w, r)
			return
		}

		start := time.Now()
		rec := &statusRecorder{ResponseWriter: w, status: http.StatusOK}

		next.ServeHTTP(rec, r)

		code := strconv.Itoa(rec.status)
		labels := prometheus.Labels{
			"code":     code,
			"method":   r.Method,
			"endpoint": r.URL.Path,
		}
		httpRequestsTotal.With(labels).Inc()
		httpRequestDuration.With(labels).Observe(time.Since(start).Seconds())
	})
}

func getEnv(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func writeJSON(w http.ResponseWriter, code int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(payload)
}
