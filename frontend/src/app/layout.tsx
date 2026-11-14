import type { Metadata } from "next";
import { Doto, Geist, Geist_Mono, Mukta } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "@/lib/auth-context";
import { ThemeProvider, themeBootScript } from "@/lib/theme";

// Geist carries the interface and the display sizes. It has no Devanagari,
// so Mukta sits behind it in the stack: Hindi in a transcript or task falls
// through to Mukta instead of a system font. Doto is the dot-matrix face for
// headline counts only.
const sans = Geist({
  variable: "--font-geist",
  subsets: ["latin"],
});

const devanagari = Mukta({
  variable: "--font-devanagari",
  subsets: ["devanagari"],
  weight: ["400", "500", "600", "700"],
});

const doto = Doto({
  variable: "--font-doto",
  subsets: ["latin"],
  weight: ["600", "700", "800"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: { default: "Wilco", template: "%s · Wilco" },
  description: "Wilco joins your meetings, hears English and Hinglish, and turns them into owners, tasks and decisions your team can search. Heard. Will comply.",
  metadataBase: new URL(process.env.NEXT_PUBLIC_APP_URL || "https://wilco.example.com"),
  icons: {
    icon: [{ url: "/wilco-favicon.png", type: "image/png", sizes: "96x96" }],
    shortcut: "/wilco-favicon.png",
    apple: [{ url: "/wilco-apple-touch-icon.png", sizes: "180x180" }],
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
      className={`${sans.variable} ${devanagari.variable} ${doto.variable} ${geistMono.variable} h-full antialiased`}
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
