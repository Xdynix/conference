#!/bin/sh
# Strip trailing slash from SUBPATH before envsubst processes the nginx template.
export SUBPATH="${SUBPATH%/}"
