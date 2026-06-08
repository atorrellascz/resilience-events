package service

import (
	"context"
	"errors"
	"testing"

	"github.com/atorrellascz/resilience-events/catalog-api/domain"
)

// fakeRepo is an in-memory test double for the Repository port.
// It records what it was called with so tests can assert behavior,
// without touching MongoDB (same idea as the Moq mock in the .NET tests).
type fakeRepo struct {
	added      *domain.MonitoredSystem   // last entity passed to Add
	lastLimit  int64                     // last limit passed to List
	listResult []*domain.MonitoredSystem // what List returns
	pingErr    error                     // what Ping returns
}

func (f *fakeRepo) Add(ctx context.Context, sys *domain.MonitoredSystem) (*domain.MonitoredSystem, error) {
	f.added = sys
	return sys, nil
}

func (f *fakeRepo) List(ctx context.Context, limit int64) ([]*domain.MonitoredSystem, error) {
	f.lastLimit = limit
	return f.listResult, nil
}

func (f *fakeRepo) Ping(ctx context.Context) error {
	return f.pingErr
}

func TestCreate_ValidInput_PersistsAndReturns(t *testing.T) {
	repo := &fakeRepo{}
	svc := NewCatalogService(repo)

	sys, err := svc.Create(context.Background(), "payments-db", "high", []string{"prod"})

	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if repo.added == nil {
		t.Fatal("expected repo.Add to be called, but it was not")
	}
	if sys.Name != "payments-db" {
		t.Errorf("name = %q, want %q", sys.Name, "payments-db")
	}
	if sys.Criticality != "high" {
		t.Errorf("criticality = %q, want %q", sys.Criticality, "high")
	}
	if sys.CreatedAt.IsZero() {
		t.Error("expected CreatedAt to be set by the domain factory")
	}
}

func TestCreate_EmptyName_ReturnsErrorAndDoesNotPersist(t *testing.T) {
	repo := &fakeRepo{}
	svc := NewCatalogService(repo)

	_, err := svc.Create(context.Background(), "", "high", nil)

	if !errors.Is(err, domain.ErrInvalidName) {
		t.Fatalf("error = %v, want ErrInvalidName", err)
	}
	if repo.added != nil {
		t.Error("repo.Add must NOT be called when validation fails")
	}
}

func TestCreate_UnknownCriticality_NormalizesToLow(t *testing.T) {
	repo := &fakeRepo{}
	svc := NewCatalogService(repo)

	sys, err := svc.Create(context.Background(), "svc", "bogus", nil)

	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if sys.Criticality != "low" {
		t.Errorf("criticality = %q, want %q (safe default)", sys.Criticality, "low")
	}
}

func TestList_ClampsLimitToSafeRange(t *testing.T) {
	cases := []struct {
		name      string
		requested int64
		wantUsed  int64
	}{
		{"zero -> 50", 0, 50},
		{"negative -> 50", -5, 50},
		{"too high -> 50", 999, 50},
		{"valid is respected", 25, 25},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			repo := &fakeRepo{}
			svc := NewCatalogService(repo)

			if _, err := svc.List(context.Background(), tc.requested); err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if repo.lastLimit != tc.wantUsed {
				t.Errorf("repo got limit %d, want %d", repo.lastLimit, tc.wantUsed)
			}
		})
	}
}

func TestReady_PropagatesPingResult(t *testing.T) {
	// Healthy DB -> nil.
	if err := NewCatalogService(&fakeRepo{pingErr: nil}).Ready(context.Background()); err != nil {
		t.Errorf("expected nil error when DB is healthy, got %v", err)
	}
	// Unhealthy DB -> the ping error propagates.
	downErr := errors.New("mongo unreachable")
	if err := NewCatalogService(&fakeRepo{pingErr: downErr}).Ready(context.Background()); !errors.Is(err, downErr) {
		t.Errorf("expected the ping error to propagate, got %v", err)
	}
}
