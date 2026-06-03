package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"sync/atomic"
)

// Contador simple de requests (Fase 1: lo reemplaza el cliente Prometheus real).
var requests int64

// writeJSON centraliza la respuesta JSON (DRY: un solo lugar que fija headers).
func writeJSON(w http.ResponseWriter, code int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(payload)
}

func main() {
	// La URL del backend viene por env (12-factor): inyectable, no hardcodeada.
	eventsURL := os.Getenv("EVENTS_API_URL")
	if eventsURL == "" {
		eventsURL = "http://events-api:8080"
	}

	mux := http.NewServeMux()

	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		atomic.AddInt64(&requests, 1)
		writeJSON(w, http.StatusOK, map[string]string{
			"service":   "edge-gateway",
			"language":  "Go",
			"role":      "reverse proxy + resilience + request journaling",
			"backend":   eventsURL,
			"message":   "Hello from edge-gateway - Phase 0 stub",
		})
	})

	mux.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "healthy"})
	})

	mux.HandleFunc("/ready", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "ready"})
	})

	// /metrics mínimo en formato de exposición Prometheus (válido y scrapeable).
	mux.HandleFunc("/metrics", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/plain; version=0.0.4")
		fmt.Fprint(w, "# HELP gateway_up Service up indicator\n# TYPE gateway_up gauge\ngateway_up 1\n")
		fmt.Fprintf(w, "# HELP gateway_requests_total Total HTTP requests handled\n# TYPE gateway_requests_total counter\ngateway_requests_total %d\n", atomic.LoadInt64(&requests))
	})

	addr := ":8080"
	log.Printf("edge-gateway listening on %s, backend=%s", addr, eventsURL)
	log.Fatal(http.ListenAndServe(addr, mux))
}