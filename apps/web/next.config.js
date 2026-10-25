/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  compress: true,
  allowedDevOrigins: [
    "signalforge.tail5c3b8b.ts.net",
    "*.tail5c3b8b.ts.net",
    "*.ts.net",
    "*.ngrok-free.dev",
    "localhost:3000",
    "127.0.0.1:3000",
  ],
  async rewrites() {
    return [
      {
        source: '/api/v1/:path*',
        // Route client requests to the backend container
        destination: 'http://api:8000/api/v1/:path*',
      },
    ]
  },
};

module.exports = nextConfig;
