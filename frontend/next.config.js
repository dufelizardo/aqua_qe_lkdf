/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: 'standalone',
  experimental: { serverComponentsExternalPackages: ['monaco-editor'] },
}
module.exports = nextConfig
