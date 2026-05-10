import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Morphanus Web",
  description: "Zero-install browser workflow for camera preview and short exports.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
