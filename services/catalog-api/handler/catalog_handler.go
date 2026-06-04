package handler

import (
	"encoding/json"
	"errors"
	"net/http"
	"strconv"

	"github.com/atorrellascz/resilience-events/catalog-api/domain"
	"github.com/atorrellascz/resilience-events/catalog-api/service"
)

// CatalogHandler translates HTTP <-> service. Contains NO business logic.
type CatalogHandler struct {
	svc *service.CatalogService
}

func NewCatalogHandler(svc *service.CatalogService) *CatalogHandler {
	return &CatalogHandler{svc: svc}
}

// createSystemRequest: the input DTO (separate from the domain entity).
type createSystemRequest struct {
	Name        string   `json:"name"`
	Criticality string   `json:"criticality"`
	Tags        []string `json:"tags"`
}

// Register wires the routes into the mux.
func (h *CatalogHandler) Register(mux *http.ServeMux) {
	mux.HandleFunc("POST /api/systems", h.create)
	mux.HandleFunc("GET /api/systems", h.list)
}

func (h *CatalogHandler) create(w http.ResponseWriter, r *http.Request) {
	var req createSystemRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}

	sys, err := h.svc.Create(r.Context(), req.Name, req.Criticality, req.Tags)
	if err != nil {
		// Map DOMAIN errors to HTTP status codes (errors.Is, idiomatic).
		if errors.Is(err, domain.ErrInvalidName) {
			writeError(w, http.StatusBadRequest, err.Error())
			return
		}
		writeError(w, http.StatusInternalServerError, "could not create system")
		return
	}

	writeJSON(w, http.StatusCreated, sys) // 201 Created
}

func (h *CatalogHandler) list(w http.ResponseWriter, r *http.Request) {
	limit := int64(50)
	if q := r.URL.Query().Get("limit"); q != "" {
		if parsed, err := strconv.ParseInt(q, 10, 64); err == nil {
			limit = parsed
		}
	}

	systems, err := h.svc.List(r.Context(), limit)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not list systems")
		return
	}

	writeJSON(w, http.StatusOK, systems)
}

// ── response helpers (DRY) ──

func writeJSON(w http.ResponseWriter, code int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(payload)
}

func writeError(w http.ResponseWriter, code int, msg string) {
	writeJSON(w, code, map[string]string{"error": msg})
}
