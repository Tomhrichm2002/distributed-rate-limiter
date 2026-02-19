#!/bin/bash

echo "🚀 Starting Distributed Rate Limiter..."
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker and try again."
    exit 1
fi

echo "✅ Docker is running"
echo ""

# Start services
echo "📦 Starting services with Docker Compose..."
docker-compose up -d

echo ""
echo "⏳ Waiting for services to be healthy..."
sleep 10

# Check health
echo ""
echo "🏥 Checking service health..."
curl -s http://localhost:5000/health | python3 -m json.tool

echo ""
echo ""
echo "✨ Rate Limiter is ready!"
echo ""
echo "📍 Available endpoints:"
echo "   API Gateway:  http://localhost:5000"
echo "   Dashboard:    http://localhost:8080"
echo "   Health Check: http://localhost:5000/health"
echo ""
echo "🧪 Test the rate limiter:"
echo "   curl http://localhost:5000/api/data"
echo ""
echo "📊 View dashboard:"
echo "   open http://localhost:8080"
echo ""
echo "🔍 View logs:"
echo "   docker-compose logs -f gateway"
echo ""
echo "🛑 Stop services:"
echo "   docker-compose down"
echo ""
