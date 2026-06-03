package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"sync/atomic"
)

// Phase 0: stdlib stub. Phase 1 adds: the official MongoDB client,
// handler -> service -> repository layers, and the real Prometheus client.
var requests int64

func writeJSON(w http.ResponseWriter, code int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(payload)
}

func main() {
	// The Mongo URI comes from env (12-factor), not hardcoded.
	mongoURI := os.Getenv("MONGO_URI")
	if mongoURI == "" {
		mongoURI = "mongodb://mongodb:27017"
	}

	mux := http.NewServeMux()

	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt64(&requests, 1)
		writeJSON(w, http.StatusOK, map[string]string{
			"service":  "catalog-api",
			"language": "Go",
			"domain":   "monitored-systems metadata",
			"backend":  mongoURI,
			"message":  "Hello from catalog-api - Phase 0 stub",
		})
	})

	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "healthy"})
	})

	mux.HandleFunc("/ready", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "ready"})
	})

	mux.HandleFunc("/metrics", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/plain; version=0.0.4")
		fmt.Fprint(w, "# HELP catalog_up Service up indicator\n# TYPE catalog_up gauge\ncatalog_up 1\n")
		fmt.Fprintf(w, "# HELP catalog_requests_total Total HTTP requests handled\n# TYPE catalog_requests_total counter\ncatalog_requests_total %d\n", atomic.LoadInt64(&requests))
	})

	addr := ":8080"
	log.Printf("catalog-api listening on %s, mongo=%s", addr, mongoURI)
	log.Fatal(http.ListenAndServe(addr, mux))
}
