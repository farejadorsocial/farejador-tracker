// Comunicação com o backend. Toda escrita leva o cabeçalho anti-CSRF "X-Farejador".
let aoExpirar = () => {};
export function quandoSessaoExpirar(fn) { aoExpirar = fn; }

export async function api(caminho, opcoes) {
  const o = Object.assign({ headers: {}, credentials: "same-origin" }, opcoes || {});
  o.headers["X-Farejador"] = "1";
  if (o.body && typeof o.body !== "string") { o.body = JSON.stringify(o.body); o.headers["Content-Type"] = "application/json"; }
  const r = await fetch(caminho, o);
  let dados = null; try { dados = await r.json(); } catch (_) {}
  const rotaLogin = /\/(login|primeiro-acesso|trocar-senha)$/.test(caminho);
  if (r.status === 401 && !rotaLogin) { aoExpirar(); throw new Error("Sessão expirada"); }
  if (!r.ok) throw new Error((dados && dados.detail) || ("Erro " + r.status));
  return dados;
}
