# syntax=docker/dockerfile:1

# ---- build -------------------------------------------------------------------
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src

COPY Kodo.Analyzer.CSharp.csproj ./
RUN dotnet restore Kodo.Analyzer.CSharp.csproj

COPY . ./
RUN dotnet publish Kodo.Analyzer.CSharp.csproj -c Release -o /app/publish /p:UseAppHost=false

# ---- runtime -----------------------------------------------------------------
FROM mcr.microsoft.com/dotnet/aspnet:8.0-alpine AS runtime
WORKDIR /app

ENV ASPNETCORE_URLS=http://+:5050 \
    ASPNETCORE_ENVIRONMENT=Production \
    DOTNET_RUNNING_IN_CONTAINER=true

COPY --from=build --chown=app:app /app/publish ./

# Stateless analyzer: nothing on disk is read, so a non-root, read-only workload is enough.
USER $APP_UID

EXPOSE 5050

ENTRYPOINT ["dotnet", "Kodo.Analyzer.CSharp.dll"]
