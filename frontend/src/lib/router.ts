import { useEffect, useState } from 'react';

// Roteamento por hash (funciona com o fallback SPA do Nginx e sem dependências).
export function currentPath(): string {
  const h = window.location.hash.replace(/^#/, '');
  return h === '' ? '/' : h;
}

export function usePath(): string {
  const [path, setPath] = useState(currentPath());
  useEffect(() => {
    const on = () => setPath(currentPath());
    window.addEventListener('hashchange', on);
    return () => window.removeEventListener('hashchange', on);
  }, []);
  return path;
}

export function href(path: string): string {
  return '#' + path;
}
