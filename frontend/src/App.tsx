import { useEffect, useState } from 'react';
import { href, usePath } from './lib/router';
import { useTheme } from './lib/theme';
import { GLOBAL_DISCLAIMER } from './components/ui';
import { LOTTERIES, type Lottery } from './api/types';
import { Overview } from './pages/Overview';
import { LotteryPage } from './pages/LotteryPage';
import { ProbabilitiesPage } from './pages/Probabilities';
import { GeneratorPage } from './pages/Generator';
import { ModelsPage } from './pages/Models';
import { SimulationsPage } from './pages/Simulations';
import { HistoryPage } from './pages/History';
import { AdminPage } from './pages/Admin';

const NAV: { path: string; label: string; icon: string }[] = [
  { path: '/', label: 'Visão geral', icon: '◧' },
  { path: '/megasena', label: 'Mega-Sena', icon: '①' },
  { path: '/lotofacil', label: 'Lotofácil', icon: '②' },
  { path: '/quina', label: 'Quina', icon: '③' },
  { path: '/probabilidades', label: 'Probabilidades', icon: '∑' },
  { path: '/gerador', label: 'Gerador experimental', icon: '✦' },
  { path: '/modelos', label: 'Modelos e backtests', icon: '⚗' },
  { path: '/simulacoes', label: 'Simulações', icon: '∿' },
  { path: '/historico', label: 'Histórico', icon: '☰' },
  { path: '/admin', label: 'Administração', icon: '⚙' },
];

function isLottery(s: string | undefined): s is Lottery {
  return (LOTTERIES as readonly string[]).includes(s ?? '');
}

function Route({ path, dark }: { path: string; dark: boolean }) {
  const seg = path.split('/').filter(Boolean);
  const [first, second] = seg;
  if (seg.length === 0) return <Overview />;
  if (isLottery(first)) return <LotteryPage lottery={first} dark={dark} />;
  switch (first) {
    case 'probabilidades':
      return <ProbabilitiesPage />;
    case 'gerador':
      return <GeneratorPage suggestionId={second} />;
    case 'modelos':
      return <ModelsPage experimentId={second} dark={dark} />;
    case 'simulacoes':
      return <SimulationsPage experimentId={second} />;
    case 'historico':
      return <HistoryPage />;
    case 'admin':
      return <AdminPage />;
    default:
      return (
        <div className="state state-empty">
          Página não encontrada. <a href={href('/')}>Voltar à visão geral</a>.
        </div>
      );
  }
}

export function App() {
  const path = usePath();
  const { pref, dark, cycle } = useTheme();
  const [collapsed, setCollapsed] = useState(false);
  const [drawer, setDrawer] = useState(false);

  useEffect(() => {
    setDrawer(false);
    window.scrollTo?.(0, 0);
    const first = '/' + (path.split('/').filter(Boolean)[0] ?? '');
    const item = NAV.find((n) => n.path === first);
    document.title = (item ? item.label + ' · ' : '') + 'Loteria Analytics';
  }, [path]);

  useEffect(() => {
    if (!drawer) return;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setDrawer(false);
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [drawer]);

  const current = '/' + (path.split('/').filter(Boolean)[0] ?? '');
  const themeLabel = pref === 'auto' ? 'Tema: automático' : pref === 'light' ? 'Tema: claro' : 'Tema: escuro';

  return (
    <div className={'shell' + (collapsed ? ' collapsed' : '') + (drawer ? ' drawer-open' : '')}>
      <a className="skip" href="#conteudo">
        Ir para o conteúdo
      </a>
      <header className="topbar">
        <button type="button" className="btn btn-icon menu-btn" aria-label="Abrir menu" aria-expanded={drawer} onClick={() => setDrawer((d) => !d)}>
          ☰
        </button>
        <span className="brand-mobile">Loteria Analytics</span>
        <button type="button" className="btn btn-ghost" onClick={cycle} aria-label={themeLabel + '. Clique para alternar.'}>
          {pref === 'auto' ? '◐' : pref === 'light' ? '☀' : '☾'} <span className="hide-sm">{themeLabel.replace('Tema: ', '')}</span>
        </button>
      </header>
      <nav className="sidebar" aria-label="Navegação principal">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            ◈
          </span>
          <span className="nav-text brand-name">Loteria Analytics</span>
        </div>
        <ul>
          {NAV.map((n) => (
            <li key={n.path}>
              <a href={href(n.path)} aria-current={current === n.path ? 'page' : undefined} title={n.label}>
                <span className="nav-icon" aria-hidden="true">
                  {n.icon}
                </span>
                <span className="nav-text">{n.label}</span>
              </a>
            </li>
          ))}
        </ul>
        <button
          type="button"
          className="btn btn-ghost collapse-btn"
          onClick={() => setCollapsed((c) => !c)}
          aria-pressed={collapsed}
          aria-label={collapsed ? 'Expandir menu lateral' : 'Recolher menu lateral'}
        >
          {collapsed ? '»' : '« Recolher'}
        </button>
      </nav>
      {drawer && <div className="scrim" onClick={() => setDrawer(false)} aria-hidden="true" />}
      <div className="main-col">
        <main id="conteudo" tabIndex={-1}>
          <Route path={path} dark={dark} />
        </main>
        <footer className="footer" role="contentinfo">
          <p>{GLOBAL_DISCLAIMER}</p>
        </footer>
      </div>
    </div>
  );
}
