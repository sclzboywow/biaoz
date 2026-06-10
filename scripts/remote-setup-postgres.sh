#!/bin/bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
sudo apt-get update -qq
sudo apt-get install -y -qq postgresql postgresql-contrib
sudo systemctl enable postgresql
sudo systemctl start postgresql
sudo -u postgres psql -tc "SELECT version();"
sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='biaoz'" | grep -q 1 || sudo -u postgres psql -c "CREATE USER biaoz WITH PASSWORD 'biaoz' CREATEDB;"
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='biaoz'" | grep -q 1 || sudo -u postgres psql -c "CREATE DATABASE biaoz OWNER biaoz;"
echo postgres_ready
