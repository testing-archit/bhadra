import type { Metadata } from "next";
import { Baloo_2, Geist_Mono, Mukta } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "@/lib/auth-context";
import { ThemeProvider, themeBootScript } from "@/lib/theme";

// Baloo 2 (headings) and Mukta (body) are both by Ek Type and both carry
// Devanagari, so Hindi and Hinglish text renders in the same family as
// English instead of falling back to a system font.
const display = Baloo_2({
  variable: "--font-display",
  subsets: ["latin", "devanagari"],
});

const body = Mukta({
  variable: "--font-body",
  subsets: ["latin", "devanagari"],
  weight: ["400", "500", "600", "700"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: { default: "Charcha", template: "%s · Charcha" },
  description: "Voice-first meeting memory for Indian teams. Speak in any language; Charcha keeps the decisions, tasks and follow-ups.",
  metadataBase: new URL(process.env.NEXT_PUBLIC_APP_URL || "https://charcha.example.com"),
  icons: {
    icon: [{ url: "/charcha-favicon.png", type: "image/png", sizes: "96x96" }],
    shortcut: "/charcha-favicon.png",
    apple: [{ url: "/charcha-apple-touch-icon.png", sizes: "180x180" }],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${display.variable} ${body.variable} ${geistMono.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeBootScript }} />
      </head>
      <body className="min-h-full flex flex-col">
        <ThemeProvider>
          <AuthProvider>{children}</AuthProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
