# ── build stage: compile with the full SDK ──
FROM mcr.microsoft.com/dotnet/sdk:10.0-alpine AS build
WORKDIR /src
COPY events-api.csproj .
RUN dotnet restore                          # cacheable layer: only re-downloads if the .csproj changes
COPY . .
RUN dotnet publish -c Release -o /app /p:UseAppHost=false

# ── runtime stage: minimal image, runtime only ──
FROM mcr.microsoft.com/dotnet/aspnet:10.0-alpine AS final
WORKDIR /app
ENV ASPNETCORE_URLS=http://+:8080 \
    DOTNET_RUNNING_IN_CONTAINER=true \
    DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=true
COPY --from=build /app .
USER app
EXPOSE 8080
ENTRYPOINT ["dotnet", "events-api.dll"]
