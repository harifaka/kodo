# syntax=docker/dockerfile:1
# Kodo ephemeral C# builder (Phase 9).
# Non-root, offline-capable: the NuGet cache is pre-warmed with the Phase 4 template packages plus
# the Windows desktop targeting pack WPF projects need for `dotnet restore` on Linux.
FROM mcr.microsoft.com/dotnet/sdk:8.0-alpine

ENV DOTNET_CLI_TELEMETRY_OPTOUT=1 \
    DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1 \
    DOTNET_NOLOGO=1 \
    DOTNET_CLI_HOME=/home/builder \
    NUGET_PACKAGES=/home/builder/.nuget/packages

RUN addgroup -g 10001 builder \
    && adduser -D -u 10001 -G builder builder \
    && mkdir -p /workspace /home/builder/.nuget \
    && chown -R 10001:10001 /workspace /home/builder

USER builder
WORKDIR /home/builder/seed
COPY --chown=10001:10001 seed/wpf/ ./wpf/
COPY --chown=10001:10001 seed/tests/ ./tests/
RUN dotnet restore wpf/Seed.Wpf.csproj \
    && dotnet restore tests/Seed.Tests.csproj \
    && dotnet build tests/Seed.Tests.csproj --no-restore -v quiet

USER root
RUN rm -rf /home/builder/seed
USER builder
WORKDIR /workspace

CMD ["dotnet", "build", "-p:EnableWindowsTargeting=true"]
