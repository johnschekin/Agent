import type { Metadata } from "next";
import "./globals.css";
import { Sidebar } from "@/components/layout/Sidebar";
import { Providers } from "@/components/layout/Providers";

export const metadata: Metadata = {
  title: "Corpus Dashboard — Pattern Discovery Swarm",
  description:
    "Foundry-class analytical workbench for leveraged credit agreement corpus analysis",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body className="antialiased">
        <Providers>
          <Sidebar />
          <main className="ml-sidebar h-screen overflow-hidden">{children}</main>
        </Providers>
      </body>
    </html>
  );
}
