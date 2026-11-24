# syntax=docker/dockerfile:1
# Kodo ephemeral Node.js/TypeScript builder (Phase 9).
# Non-root, offline-capable: the toolchain and the Phase 4 template dependencies live in a shared
# cache. The entrypoint links that cache into /workspace/node_modules only when the staged project
# has none, so `tsc --noEmit` (and `vitest run`) resolve types with --network=none.
FROM node:22-alpine

ENV KODO_NODE_CACHE=/opt/kodo-node-cache \
    NODE_PATH=/opt/kodo-node-cache/node_modules \
    PATH=/opt/kodo-node-cache/node_modules/.bin:$PATH \
    npm_config_update_notifier=false \
    npm_config_fund=false

RUN mkdir -p "${KODO_NODE_CACHE}" /workspace \
    && cd "${KODO_NODE_CACHE}" \
    && npm init -y > /dev/null \
    && npm install --no-audit --no-fund --loglevel=error \
        typescript@^5.6.2 \
        vitest@^2.1.2 \
        express@^4.19.2 \
        @types/express@^4.17.21 \
        @types/node@^22.7.4 \
        class-validator@^0.14.1 \
        class-transformer@^0.5.1 \
        reflect-metadata@^0.2.2 \
    && npm cache clean --force > /dev/null 2>&1

COPY --chown=10001:10001 entrypoint.sh /usr/local/bin/kodo-builder-entrypoint.sh

RUN addgroup -g 10001 builder \
    && adduser -D -u 10001 -G builder builder \
    && chmod 0755 /usr/local/bin/kodo-builder-entrypoint.sh \
    && chown -R 10001:10001 "${KODO_NODE_CACHE}" /workspace /home/builder

USER builder
WORKDIR /workspace

ENTRYPOINT ["/usr/local/bin/kodo-builder-entrypoint.sh"]
CMD ["sh", "-c", "tsc --noEmit"]
