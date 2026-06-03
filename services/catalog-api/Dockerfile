# ── build stage ──
FROM golang:1.26-alpine AS build
WORKDIR /src
COPY go.mod .
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o /catalog-api .

# ── runtime stage ──
FROM alpine:3.21 AS final
RUN adduser -D -u 10001 appuser
COPY --from=build /catalog-api /usr/local/bin/catalog-api
USER appuser
EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/catalog-api"]