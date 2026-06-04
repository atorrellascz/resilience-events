package service

import (
	"context"

	"github.com/atorrellascz/resilience-events/catalog-api/domain"
)

// Repository: the interface is defined by the CONSUMER (this service), not the repo.
// MongoRepository satisfies it automatically by having these methods
// (Go's structural duck typing) — without declaring "implements" anywhere.
type Repository interface {
	Add(ctx context.Context, sys *domain.MonitoredSystem) (*domain.MonitoredSystem, error)
	List(ctx context.Context, limit int64) ([]*domain.MonitoredSystem, error)
	Ping(ctx context.Context) error
}

// CatalogService contains the business logic. It depends on the ABSTRACTION
// (Repository), not on Mongo. In tests you pass a fake; in prod, the MongoRepository.
type CatalogService struct {
	repo Repository
}

// NewCatalogService: dependency injection via constructor.
func NewCatalogService(repo Repository) *CatalogService {
	return &CatalogService{repo: repo}
}

// Create validates (via the domain) and persists a monitored system.
func (s *CatalogService) Create(ctx context.Context, name, criticality string, tags []string) (*domain.MonitoredSystem, error) {
	// The domain factory validates and creates an object that is valid by construction.
	sys, err := domain.NewMonitoredSystem(name, criticality, tags)
	if err != nil {
		return nil, err
	}
	return s.repo.Add(ctx, sys)
}

// List returns the systems, with the limit clamped defensively.
func (s *CatalogService) List(ctx context.Context, limit int64) ([]*domain.MonitoredSystem, error) {
	if limit < 1 || limit > 200 {
		limit = 50 // defensive cap: never an unbounded query
	}
	return s.repo.List(ctx, limit)
}

// Ready exposes the DB health check for /ready.
func (s *CatalogService) Ready(ctx context.Context) error {
	return s.repo.Ping(ctx)
}
