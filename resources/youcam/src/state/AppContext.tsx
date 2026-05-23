// state/AppContext.tsx — Context + Provider。状態と dispatch を配布する。
//   state.apiKey の変化を api/client.ts に同期し、各 API 呼び出しが常に最新キーを使えるようにする。

import { createContext, useContext, useEffect, useReducer, type Dispatch, type ReactNode } from 'react';
import { client } from '../api/client';
import { reducer, initialState, type AppState, type Action } from './appState';

const StateContext = createContext<AppState | null>(null);
const DispatchContext = createContext<Dispatch<Action> | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState);

  // state → API 層へキーを同期（client は state を知らない純粋層なので、ここで橋渡しする）。
  useEffect(() => {
    client.setApiKey(state.apiKey);
  }, [state.apiKey]);

  return (
    <StateContext.Provider value={state}>
      <DispatchContext.Provider value={dispatch}>{children}</DispatchContext.Provider>
    </StateContext.Provider>
  );
}

export function useAppState(): AppState {
  const ctx = useContext(StateContext);
  if (!ctx) throw new Error('useAppState は AppProvider の内側で使ってください。');
  return ctx;
}

export function useAppDispatch(): Dispatch<Action> {
  const ctx = useContext(DispatchContext);
  if (!ctx) throw new Error('useAppDispatch は AppProvider の内側で使ってください。');
  return ctx;
}
