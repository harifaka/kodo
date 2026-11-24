# syntax=docker/dockerfile:1
# Kodo ephemeral Java builder (Phase 9).
# Non-root, offline-capable: the local Maven repository is pre-warmed with the Phase 4
# Spring Boot 3 template dependency set so `mvn -o test-compile` works with --network=none.
FROM maven:3.9-eclipse-temurin-21-alpine

ENV MAVEN_CONFIG=/home/builder/.m2 \
    MAVEN_OPTS="-Dmaven.repo.local=/home/builder/.m2/repository -Dstyle.color=never" \
    MAVEN_ARGS="-B -ntp"

RUN addgroup -g 10001 builder \
    && adduser -D -u 10001 -G builder builder \
    && mkdir -p /workspace /home/builder/.m2 \
    && chown -R 10001:10001 /workspace /home/builder

USER builder
WORKDIR /home/builder/seed
COPY --chown=10001:10001 pom.seed.xml pom.xml
COPY --chown=10001:10001 src ./src
# go-offline pulls plugins/dependencies; the package run warms the compiler, surefire, JUnit and
# spring-boot-maven-plugin artifacts the generated projects need at verify time.
RUN mvn -B -q dependency:go-offline && mvn -B -q package

USER root
RUN rm -rf /home/builder/seed
USER builder
WORKDIR /workspace

CMD ["mvn", "-B", "-o", "test-compile"]
