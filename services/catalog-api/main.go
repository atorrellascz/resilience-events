package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"sync/atomic"
	"time"

	"github.com/atorrellascz/resilience-events/catalog-api/handler"
	"github.com/atorrellascz/resilience-events/catalog-api/repository"
	"github.com/atorrellascz/resilience-events/catalog-api/service"
)

var requests int64

func main() {
	// ── Config from environment (12-factor) ──
	mongoURI := getEnv("MONGO_URI", "mongodb://mongodb:27017")
	dbName := getEnv("MONGO_DB", "catalog")

	// ── Connect to Mongo with a timeout (don't hang waiting) ──
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	repo, err := repository.NewMongoRepository(ctx, mongoURI, dbName)
	if err != nil {
		log.Fatalf("failed to connect to MongoDB: %v", err)
	}
	log.Printf("connected to MongoDB at %s (db=%s)", mongoURI, dbName)

	// ── Composition root: assemble the layers (manual DI) ──
	svc := service.NewCatalogService(repo)
	h := handler.NewCatalogHandler(svc)

	mux := http.NewServeMux()
	h.Register(mux) // business routes: /api/systems

	// ── Operational endpoints (same contract as the other services) ──
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "healthy"})
	})

	// REAL readiness: does Mongo respond?
	mux.HandleFunc("GET /ready", func(w http.ResponseWriter, r *http.Request) {
		if err := svc.Ready(r.Context()); err != nil {
			writeJSON(w, http.StatusServiceUnavailable,
				map[string]string{"status": "not-ready", "reason": "database unreachable"})
			return
		}
		writeJSON(w, http.StatusOK, map[string]string{"status": "ready"})
	})

	mux.HandleFunc("GET /metrics", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/plain; version=0.0.4")
		fmt.Fprint(w, "# HELP catalog_up Service up indicator\n# TYPE catalog_up gauge\ncatalog_up 1\n")
		fmt.Fprintf(w, "# HELP catalog_requests_total Total HTTP requests handled\n# TYPE catalog_requests_total counter\ncatalog_requests_total %d\n", atomic.LoadInt64(&requests))
	})

	// ── Simple middleware: counts requests for /metrics ──
	wrapped := countMiddleware(mux)

	addr := ":8080"
	log.Printf("catalog-api listening on %s", addr)
	log.Fatal(http.ListenAndServe(addr, wrapped))
}

// countMiddleware increments the counter on each request (RED: rate).
func countMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt64(&requests, 1)
		next.ServeHTTP(w, r)
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
