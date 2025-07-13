# Instagram Reel Downloader with Proxy Support

This enhanced version of the Instagram Reel Downloader includes comprehensive proxy support, specifically optimized for Indian proxy servers.

## 🌟 New Features

- **Proxy Support**: Full proxy support for both HTTP and SOCKS5 proxies
- **Indian Proxy Optimization**: Pre-configured with Indian proxy servers
- **Automatic Failover**: Automatically switches to backup proxies if primary fails
- **Proxy Rotation**: Randomly selects from available proxies for better performance
- **Proxy Testing**: Built-in proxy connectivity testing
- **Environment Variables**: Flexible configuration through environment variables

## 🚀 Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Proxies

Edit `proxy_config.py` to add your Indian proxy servers:

```python
INDIAN_PROXY_SERVERS = [
    'http://your-proxy-server:8080',
    'http://another-proxy:3128',
    'socks5://socks-proxy:1080',
]
```

### 3. Run with Proxy

```bash
python run_with_proxy.py
```

Or run directly:

```bash
python Backend.py
```

## 📖 Configuration Options

### Environment Variables

You can configure proxies using environment variables:

```bash
# Enable/disable proxy support
export PROXY_ENABLED=true

# Set primary proxy
export PRIMARY_PROXY=http://proxy-server:8080

# Set multiple proxies (comma-separated)
export PROXY_LIST=http://proxy1:8080,http://proxy2:3128,socks5://proxy3:1080

# Set timeout (seconds)
export PROXY_TIMEOUT=20

# Set retry count
export PROXY_RETRIES=3
```

### Using Docker

```bash
# Build the image
docker build -t instagram-downloader .

# Run with proxy environment variables
docker run -e PROXY_ENABLED=true -e PRIMARY_PROXY=http://proxy:8080 -p 5000:5000 instagram-downloader
```

## 🔧 API Endpoints

### New Proxy Endpoints

#### Get Proxy Configuration
```bash
GET /proxy-config
```

Response:
```json
{
  "proxy_enabled": true,
  "primary_proxy": "http://proxy-server:8080",
  "fallback_proxies_count": 5,
  "total_proxies": 5
}
```

#### Update Proxy Configuration
```bash
POST /proxy-config
Content-Type: application/json

{
  "enabled": true,
  "primary_proxy": "http://new-proxy:8080",
  "fallback_proxies": [
    "http://backup1:8080",
    "http://backup2:3128"
  ]
}
```

#### Test Proxy Connectivity
```bash
POST /test-proxy
Content-Type: application/json

{
  "proxy_url": "http://proxy-server:8080"
}
```

Response:
```json
{
  "status": "success",
  "proxy_url": "http://proxy-server:8080",
  "response": {
    "origin": "123.456.789.012"
  },
  "response_time": 1.234
}
```

### Existing Endpoints (Enhanced)

All existing endpoints now support proxy:
- `POST /get-reel-thumbnail` - Now includes `proxy_used` field
- `POST /download-reel` - Downloads through proxy
- `POST /get-reel-info` - Fetches info through proxy
- `GET /health` - Includes proxy status

## 🇮🇳 Indian Proxy Providers

### Recommended Providers

1. **ProxyMesh India**
   - HTTP/HTTPS proxies
   - Mumbai, Delhi, Bangalore locations
   - High reliability

2. **Bright Data (Luminati)**
   - Residential and datacenter proxies
   - Multiple Indian cities
   - Premium service

3. **Smartproxy**
   - Residential proxies
   - Good performance in India
   - Competitive pricing

4. **Oxylabs**
   - Datacenter and residential
   - Mumbai and Delhi locations
   - Enterprise-grade

### Free Proxy Lists

Some free proxy sources (use with caution):
- `https://www.proxy-list.download/HTTPS`
- `https://free-proxy-list.net/`
- `https://www.us-proxy.org/`

## 🛠️ Usage Examples

### Basic Usage with Proxy

```python
import requests

# Download reel with proxy
response = requests.post('http://localhost:5000/download-reel', json={
    'url': 'https://www.instagram.com/reel/ABC123/',
    'quality': 'high'
})

# Get thumbnail with proxy info
response = requests.post('http://localhost:5000/get-reel-thumbnail', json={
    'url': 'https://www.instagram.com/reel/ABC123/'
})

print(response.json()['proxy_used'])  # True if proxy was used
```

### Test Proxy Connectivity

```python
import requests

# Test specific proxy
response = requests.post('http://localhost:5000/test-proxy', json={
    'proxy_url': 'http://your-proxy:8080'
})

print(response.json())
```

### Update Proxy Configuration

```python
import requests

# Update proxy settings
response = requests.post('http://localhost:5000/proxy-config', json={
    'enabled': True,
    'primary_proxy': 'http://new-proxy:8080',
    'fallback_proxies': [
        'http://backup1:8080',
        'http://backup2:3128'
    ]
})
```

## 🐛 Troubleshooting

### Common Issues

1. **Proxy Connection Timeout**
   - Increase timeout: `export PROXY_TIMEOUT=30`
   - Check proxy server status
   - Try different proxy

2. **Instagram Rate Limiting**
   - Use residential proxies
   - Implement request delays
   - Rotate proxies frequently

3. **Proxy Authentication**
   - Use format: `http://username:password@proxy:port`
   - Ensure credentials are correct

4. **SOCKS5 Proxy Issues**
   - Install `pysocks`: `pip install pysocks`
   - Use format: `socks5://proxy:port`

### Debug Mode

Enable debug logging:

```bash
export FLASK_DEBUG=1
python Backend.py
```

### Test Proxy Connectivity

```bash
python proxy_config.py
```

## 🔒 Security Considerations

1. **Proxy Security**
   - Use HTTPS proxies when possible
   - Avoid free proxies for sensitive operations
   - Monitor proxy logs

2. **Authentication**
   - Keep proxy credentials secure
   - Use environment variables for secrets
   - Rotate credentials regularly

3. **Rate Limiting**
   - Respect Instagram's rate limits
   - Implement delays between requests
   - Monitor for IP blocking

## 📊 Performance Tips

1. **Proxy Selection**
   - Use geographically close proxies
   - Test proxy speed regularly
   - Remove slow/unreliable proxies

2. **Caching**
   - Enable caching for better performance
   - Cache duration: 1 hour (configurable)
   - Clear cache if needed: `POST /clear-cache`

3. **Concurrent Requests**
   - Limit concurrent downloads
   - Use different proxies for parallel requests
   - Monitor proxy bandwidth

## 🚀 Deployment

### Local Development

```bash
python run_with_proxy.py
```

### Production (Gunicorn)

```bash
# With proxy environment variables
PROXY_ENABLED=true PROXY_LIST=http://proxy1:8080,http://proxy2:3128 gunicorn -w 4 -b 0.0.0.0:5000 Backend:app
```

### Docker Production

```dockerfile
FROM python:3.9-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

ENV PROXY_ENABLED=true
ENV PROXY_TIMEOUT=20
ENV PROXY_RETRIES=3

EXPOSE 5000

CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "Backend:app"]
```

## 📝 License

This project is licensed under the MIT License.

## 🤝 Contributing

1. Fork the repository
2. Create feature branch
3. Add proxy-related improvements
4. Submit pull request

## 📞 Support

For issues related to:
- Proxy configuration: Check `proxy_config.py`
- Connection issues: Test with `python proxy_config.py`
- API issues: Check `/health` endpoint

---

**Note**: Replace example proxy URLs with your actual proxy servers. Free proxies may be unreliable and should be used for testing only.