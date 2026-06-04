package domain

import "time"

// MonitoredSystem is the central entity: a system the platform watches.
// Pure Go: it knows NOTHING about MongoDB or HTTP. The `bson`/`json` tags are
// serialization metadata (a pragmatic compromise noted below).
type MonitoredSystem struct {
	ID          string    `bson:"_id,omitempty" json:"id"`
	Name        string    `bson:"name" json:"name"`
	Criticality string    `bson:"criticality" json:"criticality"` // low | medium | high
	Tags        []string  `bson:"tags" json:"tags"`
	CreatedAt   time.Time `bson:"createdAt" json:"createdAt"`
}

// Valid severities/criticalities — domain rule.
var validCriticalities = map[string]bool{"low": true, "medium": true, "high": true}

// NewMonitoredSystem is the factory: the only way to create a valid one.
func NewMonitoredSystem(name, criticality string, tags []string) (*MonitoredSystem, error) {
	if name == "" {
		return nil, ErrInvalidName
	}
	c := normalizeCriticality(criticality)
	if tags == nil {
		tags = []string{}
	}
	return &MonitoredSystem{
		Name:        name,
		Criticality: c,
		Tags:        tags,
		CreatedAt:   time.Now().UTC(),
	}, nil
}

func normalizeCriticality(c string) string {
	if validCriticalities[c] {
		return c
	}
	return "low" // safe default if something unknown comes in
}
