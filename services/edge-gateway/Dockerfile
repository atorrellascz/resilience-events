# ── build stage ──
FROM golang:1.26-alpine AS build
WORKDIR /src
COPY go.mod .
RUN go mod download
COPY . .
# CGO_ENABLED=0 → binario estático, sin dependencias del SO. Corre en cualquier lado.
RUN CGO_ENABLED=0 GOOS=linux go build -o /edge-gateway .

# ── runtime stage ──
FROM alpine:3.21 AS final
RUN adduser -D -u 10001 appuser             # usuario no-root
COPY --from=build /edge-gateway /usr/local/bin/edge-gateway
USER appuser
EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/edge-gateway"]