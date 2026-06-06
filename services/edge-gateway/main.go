package main

import (
	"encoding/json"
	"log"
	"net/http"
	"os"
	"strconv"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

// ── Métricas RED, con los MISMOS nombres que el resto de servicios ──
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
			Buckets: prometheus.DefBuckets,
		},
		[]string{"code", "method", "endpoint"},
	)
)

func init() {
	prometheus.MustRegister(httpRequestsTotal, httpRequestDuration)
}

func writeJSON(w http.ResponseWriter, code int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(payload)
}

func main() {
	eventsURL := os.Getenv("EVENTS_API_URL")
	if eventsURL == "" {
		eventsURL = "http://events-api:8080"
	}

	mux := http.NewServeMux()

	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{
			"service":  "edge-gateway",
			"language": "Go",
			"role":     "reverse proxy + resilience + request journaling",
			"backend":  eventsURL,
			"message":  "Hello from edge-gateway - Phase 0 stub",
		})
	})

	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "healthy"})
	})

	mux.HandleFunc("/ready", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "ready"})
	})

	// El handler oficial de Prometheus expone TODAS las métricas registradas.
	mux.Handle("/metrics", promhttp.Handler())

	// Middleware que mide cada request (rate, errores, duración).
	wrapped := metricsMiddleware(mux)

	addr := ":8080"
	log.Printf("edge-gateway listening on %s, backend=%s", addr, eventsURL)
	log.Fatal(http.ListenAndServe(addr, wrapped))
}

// statusRecorder captura el código de estado para etiquetar las métricas.
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
