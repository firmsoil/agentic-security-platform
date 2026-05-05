# Placeholder — real Rego policies land in Phase 2.
# OPA needs at least one policy file in the bundle directory to run.
# Keeping this file lets `docker compose up` succeed on day one.

package asp.platform

# Always allow in v0.1. The real pipeline gates turn on in Phase 2.
default allow := true
