package domain

import "errors"

// Domain errors — the handler will translate them to HTTP status codes.
var (
	ErrInvalidName = errors.New("system name is required")
	ErrNotFound    = errors.New("monitored system not found")
)
