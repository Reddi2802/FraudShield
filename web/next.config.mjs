/** @type {import('next').NextConfig} */
const nextConfig = {
  // Static export: `npm run build` writes ./out, which FastAPI serves (api/main.py). No Node server at runtime.
  output: 'export',
  images: { unoptimized: true },
}

export default nextConfig
