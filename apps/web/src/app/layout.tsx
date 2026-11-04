import type { Metadata, Viewport } from 'next';
import { Bricolage_Grotesque, Inter } from 'next/font/google';
import type { ReactNode } from 'react';

import { SiteFooter } from '@/components/site-footer';
import { SiteNav } from '@/components/site-nav';

import './globals.css';

/**
 * Bricolage Grotesque for headings and numbers, Inter for text, both variable and self-hosted by next/font at
 * build time so no reader's browser asks Google for a font. Both follow the size through their optical-size axes:
 * the hero gets the display cut, small labels the open one.
 */
const display = Bricolage_Grotesque({ subsets: ['latin'], display: 'swap', variable: '--font-display', axes: ['opsz'] });
const text = Inter({ subsets: ['latin'], display: 'swap', variable: '--font-text', axes: ['opsz'] });

export const metadata: Metadata = {
  title: { default: 'Hush IQ: how loud is this apartment, for the way you sleep', template: '%s · Hush IQ' },
  description:
    'Paste a NYC listing. A Meta model reads it for the apartment, the city’s own data scores the noise around it, and three taps say what keeps you up. One verdict against Manhattan, every line cited.',
  icons: { icon: '/hushiq-logo-512.png', apple: '/hushiq-logo-512.png' },
  openGraph: { type: 'website', siteName: 'Hush IQ', images: [{ url: '/hushiq-logo-512.png', width: 512, height: 512 }] },
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  colorScheme: 'light dark',
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#ffffff' },
    { media: '(prefers-color-scheme: dark)', color: '#0b0a10' },
  ],
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`${display.variable} ${text.variable}`}>
      <body>
        <SiteNav />
        <main>{children}</main>
        <SiteFooter />
      </body>
    </html>
  );
}
