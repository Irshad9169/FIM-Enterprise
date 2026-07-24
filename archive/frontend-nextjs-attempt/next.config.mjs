/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'export',
  distDir: '../web',
  images: {
    unoptimized: true,
  },
  trailingSlash: true,
};

export default nextConfig;
