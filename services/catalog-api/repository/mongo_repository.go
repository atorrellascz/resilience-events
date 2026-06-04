package repository

import (
	"context"
	"errors"
	"time"

	"github.com/atorrellascz/resilience-events/catalog-api/domain"
	"go.mongodb.org/mongo-driver/bson"
	"go.mongodb.org/mongo-driver/mongo"
	"go.mongodb.org/mongo-driver/mongo/options"
)

// MongoRepository implements persistence on MongoDB.
// The 'service' package will define the INTERFACE that this struct satisfies (Go style).
type MongoRepository struct {
	collection *mongo.Collection
}

// NewMongoRepository connects to Mongo and returns the ready repo.
func NewMongoRepository(ctx context.Context, uri, dbName string) (*MongoRepository, error) {
	client, err := mongo.Connect(ctx, options.Client().ApplyURI(uri))
	if err != nil {
		return nil, err
	}
	// Verify the connection for real (Connect does not guarantee the server responds).
	if err := client.Ping(ctx, nil); err != nil {
		return nil, err
	}
	coll := client.Database(dbName).Collection("monitored_systems")
	return &MongoRepository{collection: coll}, nil
}

func (r *MongoRepository) Add(ctx context.Context, sys *domain.MonitoredSystem) (*domain.MonitoredSystem, error) {
	res, err := r.collection.InsertOne(ctx, sys)
	if err != nil {
		return nil, err
	}
	// Mongo generates the _id; we capture it back into the entity.
	if oid, ok := res.InsertedID.(interface{ Hex() string }); ok {
		sys.ID = oid.Hex()
	}
	return sys, nil
}

func (r *MongoRepository) List(ctx context.Context, limit int64) ([]*domain.MonitoredSystem, error) {
	opts := options.Find().
		SetSort(bson.D{{Key: "createdAt", Value: -1}}). // most recent first
		SetLimit(limit)

	cursor, err := r.collection.Find(ctx, bson.D{}, opts)
	if err != nil {
		return nil, err
	}
	defer cursor.Close(ctx)

	results := []*domain.MonitoredSystem{}
	if err := cursor.All(ctx, &results); err != nil {
		return nil, err
	}
	return results, nil
}

// Ping for /ready: does Mongo respond?
func (r *MongoRepository) Ping(ctx context.Context) error {
	ctx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()
	return r.collection.Database().Client().Ping(ctx, nil)
}

// In case InsertedID is not of the expected type (defensive).
var ErrUnexpectedID = errors.New("unexpected inserted id type")
