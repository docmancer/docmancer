import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import "./globals.css";

export const metadata = {
  title: "Docmancer",
  description: "Your private AI agent for memory across coding agents.",
  icons: {
    icon: "/wizard-logo.png",
    shortcut: "/wizard-logo.png",
    apple: "/wizard-logo.png",
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning className={`${GeistSans.variable} ${GeistMono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
