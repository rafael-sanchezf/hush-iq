import type { Metadata, Viewport } from 'next';
import { Nunito, Nunito_Sans } from 'next/font/google';
import type { ReactNode } from 'react';

import { SiteFooter } from '@/components/site-footer';
import { SiteNav } from '@/components/site-nav';

import './globals.css';

/**
 * The app's type is SF Pro Rounded for numbers and headings and SF Pro for text. Apple devices get exactly
 * that (`ui-rounded`, `-apple-system` lead the stacks in globals.css); everywhere else falls back to Nunito
 * and Nunito Sans, self-hosted by next/font at build time so no reader's browser asks Google for a font.
 */
const nunito = Nunito({ subsets: ['latin'], weight: ['700', '800'], display: 'swap', variable: '--font-nunito' });
const nunitoSans = Nunito_Sans({ subsets: ['latin'], display: 'swap', variable: '--font-nunito-sans' });

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
    <html lang="en" className={`${nunito.variable} ${nunitoSans.variable}`}>
      <body>
        <SiteNav />
        <main>{children}</main>
        <SiteFooter />
      </body>
    </html>
  );
}
