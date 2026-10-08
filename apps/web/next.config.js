/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      {
        source: '/api/v1/:path*',
        // Route client requests to the backend container
        destination: (process.env.API_URL || 'http://api:8000') + '/api/v1/:path*',
      },
    ]
  },
};

module.exports = nextConfig;
