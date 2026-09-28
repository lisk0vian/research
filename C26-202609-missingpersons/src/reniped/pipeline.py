"""Orchestration of the full pipeline. Each stage receives and returns the context `ctx`.

Stages and manuscript sections:
  stage_init            plan freeze and SHA-256 lock                      (Section 4.7)
  stage_data            data integrity, territory-month panel             (Section 3)
  stage_priority        rates and priority territories                    (4.1, 5.1; Figs. 2-3)
  stage_features        features by temporal fold                         (4.2; Table 1)
  stage_k               choice of K                                       (4.3, 5.2; Fig. 4a-c)
  stage_algorithms      multi-algorithm clustering and state profiles     (4.3, 5.2; Fig. 4d)
  stage_audit           territorial-identity leakage audit                (4.6, 5.5; Table 3A)
  stage_temporal        temporal transfer to 2024 and 2025                (4.5, 5.4)
  stage_spatial         global Moran, local Gi*/LISA with FDR             (4.4, 5.3; Table 2)
  stage_multiverse      specification multiverse M1 and M2                (4.6, 5.5; Fig. 5, Table 3B)
  stage_article_figures manuscript Figs. 1-5 (ES and EN)

Console messages, table names and column names are in Spanish (see the glossary in README.md).

Usage without a notebook:  python run_all.py   (requires the data in data/raw and data/external)
"""
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import adjusted_rand_score

from . import __version__
from .audit import identity_proxy_audit, unit_cluster_table
from .clustering import (LabeledKMeans, fit_algorithms, k_selection_table, make_scaler,
                         select_k, bootstrap_stability)
from .config import PLAN, freeze_plan
from .features import build_fold_features, design_diagnostics, model_matrix
from .figures import k_selection_figure, profile_figure
from .io_utils import load_raw, sha256_file
from .maps import choropleth, gi_map, study_area_map
from .panel import build_panel, national_rates, unit_rates
from .population import build_units, read_inei
from .prioridad import annual_rr_table, priority_summary, priority_table
from .results import ResultsStore, records
from .spatial import (build_weights, eb_moran_rate, global_moran, leave_one_out_moran,
                      load_units_geometry, local_statistics, neighbours_table)
from .temporal import evaluate_year, yearly_shares


def data_paths(root, plan=PLAN):
    """Canonical paths of the three input files."""
    d = plan["datos"]
    return {"csv": root / "data/raw" / d["csv_reniped"]["nombre_canonico"],
            "xlsx": root / "data/external" / d["xlsx_inei"]["nombre_canonico"],
            "geo": root / "data/external" / d["geometria"]["nombre_canonico"]}


def _t_index(df):
    return (df["ANO"] - df["ANO"].min()) * 12 + df["MES"]


# ---------------------------------------------------------------- stage 0
def stage_init(root, plan=PLAN):
    """Freeze the analysis plan, check its SHA-256 lock and open the results store."""
    root = Path(root)
    sha, fixed = freeze_plan(root, plan)
    res = ResultsStore(root / "results")
    res.set("paquete", {"version": __version__})
    res.set("plan", {"version": plan["version_plan"], "sha256": sha, "fijado_utc": fixed,
                     "estado": plan["estado"]})
    print(f"Plan {plan['version_plan']} congelado | SHA-256 {sha[:16]}… | {plan['estado']}")
    return {"root": root, "plan": plan, "res": res, "seed": plan["semilla"],
            "paths": data_paths(root, plan)}


# ---------------------------------------------------------------- stage 1
def stage_data(ctx):
    """Verify input hashes, read RENIPED and INEI, build the panel and check that the
    observed coverage gaps equal the documented ones (Section 3.3)."""
    plan, res, paths = ctx["plan"], ctx["res"], ctx["paths"]
    with res.timer("1_datos_y_panel"):
        for key, meta in (("csv", plan["datos"]["csv_reniped"]), ("xlsx", plan["datos"]["xlsx_inei"])):
            if not paths[key].exists():
                raise FileNotFoundError(f"Falta {paths[key]}")
            if sha256_file(paths[key]) != meta["sha256"]:
                raise ValueError(f"{paths[key].name}: SHA-256 distinto al del plan")
        df, audit = load_raw(paths["csv"], plan["datos"]["csv_reniped"]["sha256"],
                             plan["datos"]["csv_reniped"]["codificacion"])
        pop = build_units(read_inei(paths["xlsx"]), plan["datos"]["anios"])
        panel = build_panel(df, pop, plan["datos"]["anios"], plan["huecos_documentados"])

        obs = panel.loc[~panel.TIENE_FILAS_FUENTE, ["DPTO_KEY", "ANO", "MES"]]
        doc = pd.DataFrame(plan["huecos_documentados"])[["DPTO_KEY", "ANO", "MES"]]
        key = ["DPTO_KEY", "ANO", "MES"]
        if not obs.sort_values(key).reset_index(drop=True).equals(
                doc.sort_values(key).reset_index(drop=True)):
            raise ValueError("Los huecos observados no coinciden con los documentados")

        rates = unit_rates(panel, plan["datos"]["anios"]).sort_values(
            "TASA_10K_EXPOSICION_OBSERVADA", ascending=False)
        nat = national_rates(rates)
        root = ctx["root"]
        pop.to_csv(root / "data/processed/poblacion_26_unidades.csv", index=False, encoding="utf-8-sig")
        panel.to_csv(root / "data/processed/panel_departamento_mes.csv", index=False, encoding="utf-8-sig")
        res.table("T01_tasas_departamentales_2019_2025", rates)
        res.set("datos.reniped", audit)
        res.set("datos.poblacion", {"unidades": int(pop.DPTO_KEY.nunique()),
                                    "personas_anio_total": int(pop.POBLACION.sum()),
                                    "regla_lima": "LIMA METROPOLITANA = 150100; REGION LIMA = 150000 - 150100"})
        res.set("panel", {
            "filas": int(len(panel)), "observadas": int(panel.TIENE_FILAS_FUENTE.sum()),
            "sin_filas_fuente": int((~panel.TIENE_FILAS_FUENTE).sum()),
            "total_reportes_conservado": int(panel.REPORTES.sum()),
            "tasa_nacional_10k_personas_anio": nat,
            "definicion_tasas": plan["tasas"],
            "meses_nacionales_incompletos": sorted({f"{a}-{m:02d}" for a, m in panel.loc[
                panel.MES_NACIONAL_INCOMPLETO, ["ANO", "MES"]].itertuples(index=False)})})
    print(f"CSV: {audit['filas']:,} filas | {audit['total_reportes']:,} reportes | "
          f"panel {len(panel):,} (observadas {panel.TIENE_FILAS_FUENTE.sum():,})")
    print(f"Tasa nacional por 10 000 personas-año: exposición observada {nat['exposicion_observada']:.4f} "
          f"| total {nat['exposicion_total']:.4f}")
    ctx.update(df=df, pop=pop, panel=panel, rates=rates)
    return ctx


# ---------------------------------------------------------------- stage 2
def stage_features(ctx):
    """Features for each temporal fold (train 2019-2023/eval 2024 and train 2019-2024/eval 2025),
    with the 6-month minimum history and the 12-month sensitivity."""
    plan, res = ctx["plan"], ctx["res"]
    fp = plan["features"]
    with res.timer("2_variables_por_fold"):
        folds = {}
        for f in plan["folds"]:
            for tag, mp in (("", fp["min_prev_months"]),
                            ("_hist12", fp["min_prev_months_sensibilidad"])):
                d = build_fold_features(ctx["panel"], f["train_end"], f["eval"], mp)
                d["T_INDEX"] = _t_index(d)
                folds[f["nombre"] + tag] = {"cfg": f, "df": d, "min_prev": mp}
                if tag == "":
                    d.to_csv(ctx["root"] / f"data/processed/features_fold_{f['nombre']}.csv",
                             index=False, encoding="utf-8-sig")
        resumen, diag = {}, {}
        for name, fo in folds.items():
            resumen[name] = {}
            for esp, feats in fp["espacios"].items():
                tr, dtr = model_matrix(fo["df"], feats, "TRAIN")
                ev, dev = model_matrix(fo["df"], feats, "EVAL")
                resumen[name][esp] = {"n_train": int(len(tr)), "excluidas_train": dtr,
                                      "n_eval": int(len(ev)), "excluidas_eval": dev,
                                      "train_con_historia_parcial": int(
                                          (~tr["HISTORIA_COMPLETA_12M"]).sum())}
                if name == "principal":
                    Xs = make_scaler(plan["escalador"]).fit_transform(tr[feats].to_numpy())
                    diag[esp] = design_diagnostics(Xs, feats)
        res.set("folds", resumen)
        res.set("diseno_espacios", diag)
    for esp, dg in diag.items():
        print(f"  {esp:<24} rango {dg['rango']}/{len(dg['variables'])} | "
              f"condición {dg['numero_condicion']:.2f} | n_train {resumen['principal'][esp]['n_train']} "
              f"(historia parcial {resumen['principal'][esp]['train_con_historia_parcial']})")
    ctx["folds"] = folds
    return ctx


def _prep(ctx, fold, esp):
    """Train/eval matrices scaled with the scaler fitted on train only."""
    plan = ctx["plan"]
    feats = plan["features"]["espacios"][esp]
    fo = ctx["folds"][fold]
    tr, _ = model_matrix(fo["df"], feats, "TRAIN")
    ev, _ = model_matrix(fo["df"], feats, "EVAL")
    sc = make_scaler(plan["escalador"]).fit(tr[feats].to_numpy())
    ref = plan["features"]["variable_orden_etiquetas"]
    return (tr, ev, sc.transform(tr[feats].to_numpy()), sc.transform(ev[feats].to_numpy()),
            tr[ref].to_numpy(), ev[ref].to_numpy(), feats)


# ---------------------------------------------------------------- stage 3
def stage_k(ctx):
    """Choose K in the main space with the pre-specified gap + panel-stability rule."""
    plan, res, seed = ctx["plan"], ctx["res"], ctx["seed"]
    esp = plan["features"]["espacio_principal"]
    with res.timer("3_seleccion_K"):
        tr, _, X, _, ref, _, feats = _prep(ctx, "principal", esp)
        tab, gap = k_selection_table(X, tr[["DPTO_KEY", "T_INDEX"]], plan["seleccion_k"], seed)
        sel, tab = select_k(tab, gap, plan["seleccion_k"])
        res.table("T02_seleccion_K", tab)
        res.table("T02b_gap_desde_K1", gap)
        res.set("seleccion_k", {"espacio": esp, "fold": "principal", "n": int(len(X)), **sel,
                                "tabla": records(tab), "gap": records(gap)})
        k_selection_figure(tab, sel["K_elegido"], res.figures, "Fig_seleccion_K")
    cols = ["K", "silhouette", "ari_media_unidad", "ari_media_bloque_temporal", "ari_media_fila",
            "ESTABILIDAD_MIN", "gap", "s_k"]
    print(tab[cols].round(4).to_string(index=False))
    print(f"Gap K=1..: {gap.round(4).to_dict('records')[:3]} …")
    print(f"K* = {sel['K_elegido']} ({sel['motivo']}) | Tibshirani desde K=1: "
          f"{sel['K_tibshirani_desde_1']} | evidencia de agrupabilidad por Gap: "
          f"{sel['evidencia_agrupabilidad_gap']}")
    ctx.update(K=sel["K_elegido"], esp0=esp)
    return ctx


# ---------------------------------------------------------------- stage 4
def stage_algorithms(ctx):
    """Fit the four algorithms at K*, and save state profiles and standardized distributions."""
    plan, res, seed, K = ctx["plan"], ctx["res"], ctx["seed"], ctx["K"]
    with res.timer("4_multialgoritmo_y_perfiles"):
        tr, _, X, _, ref, _, feats = _prep(ctx, "principal", ctx["esp0"])
        labels, lk, tab = fit_algorithms(X, ref, K, plan["algoritmos"], seed)
        res.table("T03_multialgoritmo", tab)
        res.set("multialgoritmo", records(tab))
        tr = tr.assign(CLUSTER=labels["KMeans"])
        prof = tr.groupby("CLUSTER").agg(
            N=("LOG_TASA", "size"), UNIDADES=("DPTO_KEY", "nunique"),
            TASA_10K_MENSUAL_MEDIA=("TASA_10K", "mean"),
            TASA_10K_MENSUAL_MEDIANA=("TASA_10K", "median"),
            LOG_TASA_MEDIA=("LOG_TASA", "mean"),
            **{f"{f}_MEDIA": (f, "mean") for f in feats}).reset_index()
        prof_std = pd.DataFrame(lk.cluster_centers_, columns=feats).assign(CLUSTER=range(K))
        res.table("T04_perfiles_cluster", prof)
        res.table("T04b_centroides_estandarizados", prof_std)
        # v3.3.2: distribution of each standardized feature by state (Fig. 4d) and mean ± SD
        z = pd.DataFrame(np.asarray(X), columns=feats).assign(CLUSTER=labels["KMeans"])
        dist = (z.melt(id_vars="CLUSTER", var_name="VARIABLE", value_name="Z")
                .groupby(["CLUSTER", "VARIABLE"])["Z"]
                .describe(percentiles=[0.10, 0.25, 0.50, 0.75, 0.90]).reset_index())
        res.table("T04c_distribucion_estandarizada_por_estado", dist)
        mde = tr.groupby("CLUSTER").agg(
            N=("TASA_10K", "size"), UNIDADES=("DPTO_KEY", "nunique"),
            TASA_10K_MEDIA=("TASA_10K", "mean"), TASA_10K_DE=("TASA_10K", "std"),
            **{f"{f}_MEDIA": (f, "mean") for f in feats},
            **{f"{f}_DE": (f, "std") for f in feats}).reset_index()
        res.table("T04d_media_y_de_por_estado", mde)
        res.set("perfiles_media_de", records(mde))
        tr[["DPTO_KEY", "ANO", "MES", "TASA_10K", *feats, "CLUSTER"]].to_csv(
            ctx["root"] / "data/processed/etiquetas_principal.csv", index=False, encoding="utf-8-sig")
        res.set("perfiles", records(prof))
        profile_figure(prof_std, feats, res.figures, "Fig_perfiles_cluster")
    print(tab.drop(columns="nota").round(4).to_string(index=False))
    print(prof.round(4).to_string(index=False))
    ctx.update(lk0=lk, labels0=labels, tr0=tr)
    return ctx


# ---------------------------------------------------------------- stage 5
def stage_audit(ctx):
    """Identity-leakage audit in each feature space (E1 relative, E2 mixed, E3 level)."""
    plan, res, seed, K = ctx["plan"], ctx["res"], ctx["seed"], ctx["K"]
    ap = plan["auditoria_proxy"]
    with res.timer("5_auditoria_proxy"):
        rows = []
        for fold in ("principal", "principal_hist12"):
            for esp in plan["features"]["espacios"]:
                tr, _, X, _, ref, _, _ = _prep(ctx, fold, esp)
                lab = LabeledKMeans(K, seed, plan["algoritmos"]["n_init"]).fit(X, ref).labels_
                a = identity_proxy_audit(lab, tr["DPTO_KEY"].to_numpy(), tr["ANO"].to_numpy(),
                                         ap["n_perm"], seed, tuple(ap["nulos"]))
                st = bootstrap_stability(X, tr[["DPTO_KEY", "T_INDEX"]], K,
                                         plan["seleccion_k"]["bootstrap_B"], seed,
                                         plan["seleccion_k"]["n_init"], "unidad")
                rows.append({"historia": "min6" if fold == "principal" else "min12",
                             "espacio": esp, "n": int(len(X)), **a,
                             "ARI_bootstrap_unidad": st["ari_media"]})
                if fold == "principal":
                    res.table(f"T05_unidad_x_cluster_{esp}", unit_cluster_table(tr["DPTO_KEY"], lab))
        tab = pd.DataFrame(rows)
        res.table("T05_auditoria_proxy", tab)
        res.set("auditoria_proxy", records(tab))

        # agreement between min6 and min12 histories on common rows (main space)
        a6 = ctx["tr0"][["DPTO_KEY", "FECHA", "CLUSTER"]]
        tr12, _, X12, _, ref12, _, _ = _prep(ctx, "principal_hist12", ctx["esp0"])
        l12 = LabeledKMeans(K, seed, plan["algoritmos"]["n_init"]).fit(X12, ref12).labels_
        m = a6.merge(tr12[["DPTO_KEY", "FECHA"]].assign(C12=l12), on=["DPTO_KEY", "FECHA"])
        res.set("sensibilidad_historia_12m", {
            "filas_comunes": int(len(m)),
            "ARI_min6_vs_min12": float(adjusted_rand_score(m.CLUSTER, m.C12)),
            "concordancia_etiquetas": float((m.CLUSTER == m.C12).mean())})
    show = ["historia", "espacio", "n", "NMI_cluster_unidad", "NMI_nulo_p95_bloques_anuales",
            "p_perm_bloques_anuales", "fraccion_H_asociada_a_unidad",
            "unidades_con_pureza_>=0.95", "ARI_bootstrap_unidad"]
    print(tab[show].round(4).to_string(index=False))
    print(f"min6 vs min12 (espacio principal): ARI {res.data['sensibilidad_historia_12m']['ARI_min6_vs_min12']:.3f}")
    return ctx


# ---------------------------------------------------------------- stage 6
def stage_temporal(ctx):
    """Transfer the train model to the evaluation year and compare it with a refit."""
    plan, res, seed, K = ctx["plan"], ctx["res"], ctx["seed"], ctx["K"]
    n_init = plan["algoritmos"]["n_init"]
    with res.timer("6_validacion_temporal"):
        for fold in ("principal", "secundario"):
            tr, ev, Xtr, Xev, rtr, rev, _ = _prep(ctx, fold, ctx["esp0"])
            lk = LabeledKMeans(K, seed, n_init).fit(Xtr, rtr)
            lab_ev, met = evaluate_year(lk, Xev, rev, lk.labels_, seed, n_init)
            met["nota_fold"] = ctx["folds"][fold]["cfg"]["nota"]
            res.set(f"validacion_temporal.{fold}", met)
            both = pd.concat([tr.assign(CLUSTER=lk.labels_), ev.assign(CLUSTER=lab_ev)],
                             ignore_index=True)
            res.table(f"T06_proporciones_anuales_{fold}", yearly_shares(both))
            print(f"[{fold}] eval {ctx['folds'][fold]['cfg']['eval']}: n={met['n_eval']} | "
                  f"ARI transferido vs reajustado {met['ARI_transferido_vs_reajustado']:.4f} | "
                  f"JS distancia {met['JS_distancia_base2']:.4f} (divergencia {met['JS_divergencia_bits']:.4f})")
            print(f"   proporciones train {met['proporciones_train']} -> eval {met['proporciones_eval']}")
    return ctx


# ---------------------------------------------------------------- stage 7
def stage_spatial(ctx):
    """Spatial structure: queen and geodesic KNN-4 weights, global and EB Moran's I,
    local Gi* and LISA with exact conditional p-values, BH and BY corrections, leave-one-out."""
    plan, res, seed = ctx["plan"], ctx["res"], ctx["seed"]
    sp, geo = plan["espacial"], plan["datos"]["geometria"]
    perm, alpha = sp["permutaciones"], sp["alpha"]
    with res.timer("7_espacial"):
        gpath = ctx["paths"]["geo"]
        if not gpath.exists():
            urllib.request.urlretrieve(geo["url"], gpath)
        if sha256_file(gpath) != geo["sha256"]:
            raise ValueError("La capa provincial no coincide con el SHA-256 del plan.")
        units, gaudit = load_units_geometry(gpath, ctx["pop"], geo["campo_codigo_provincia"],
                                            geo["crs_metrico"])
        res.set("espacial.geometria", {**gaudit, "fuente": geo["fuente"], "sha256": geo["sha256"]})
        k = sp["pesos"]["sensibilidad"]["k"]
        W = {"queen": build_weights(units, "queen"),
             f"knn{k}_geodesico": build_weights(units, "knn_geodesico", k)}
        for wn, w in W.items():
            res.table(f"T07_vecinos_{wn}", neighbours_table(units, w))
            res.set(f"espacial.pesos.{wn}", {"n": int(w.n), "vecinos_medio": float(w.mean_neighbors),
                                             "vecinos_min": int(w.min_neighbors),
                                             "vecinos_max": int(w.max_neighbors)})

        rates = {}
        for tag, yrs in (("2019_2025", sp["periodos"]["principal"]),
                         ("2019_2024", sp["periodos"]["sensibilidad_consolidado"])):
            rates[tag] = units[["DPTO_KEY"]].merge(unit_rates(ctx["panel"], yrs), on="DPTO_KEY",
                                                   validate="one_to_one")
            res.table(f"T08_tasas_{tag}", rates[tag])

        t5 = pd.read_csv(res.tables / f"T05_unidad_x_cluster_{ctx['esp0']}.csv")
        prop_alto = units[["DPTO_KEY"]].merge(t5, on="DPTO_KEY", validate="one_to_one")[
            f"PROP_C{ctx['K'] - 1}"].to_numpy()

        rows = []
        for tag, t in rates.items():
            for wn, w in W.items():
                for var in ("TASA_10K_EXPOSICION_OBSERVADA", "TASA_10K_EXPOSICION_TOTAL", "REPORTES"):
                    rows.append({"periodo": tag, "pesos": wn, "variable": var,
                                 **global_moran(t[var], w, perm, seed)})
                rows.append({"periodo": tag, "pesos": wn, "variable": "TASA_EB_EXPOSICION_OBSERVADA",
                             **eb_moran_rate(t["REPORTES"], t["PERSONAS_ANIO_OBSERVADA"], w, perm, seed)})
        for wn, w in W.items():
            rows.append({"periodo": "train_2019_2023", "pesos": wn,
                         "variable": f"PROP_MESES_ESTADO_ALTO_{ctx['esp0']}",
                         **global_moran(prop_alto, w, perm, seed)})
        moran = pd.DataFrame(rows)
        res.table("T09_moran_global", moran)
        res.set("espacial.moran_global", records(moran))

        y = rates["2019_2025"]["TASA_10K_EXPOSICION_OBSERVADA"]
        local = {}
        for wn, w in W.items():
            loc, meta = local_statistics(units, y, w, seed, alpha)
            local[wn] = loc
            res.table(f"T10_local_{wn}", loc)
            res.set(f"espacial.local.{wn}", {
                **meta,
                "Gi_FDR": loc.groupby("Gi_clase_FDR").DPTO_KEY.apply(list).to_dict(),
                "Gi_sin_ajuste": loc.groupby("Gi_clase_sin_ajuste").DPTO_KEY.apply(list).to_dict(),
                "LISA_FDR": loc.groupby("LISA_clase_FDR").DPTO_KEY.apply(list).to_dict(),
                "LISA_BY": loc.groupby("LISA_clase_BY").DPTO_KEY.apply(list).to_dict(),
                "LIMA_METROPOLITANA": loc.loc[loc.DPTO_KEY == "LIMA METROPOLITANA"]
                                         .iloc[0].drop("DPTO_KEY").to_dict()})
        loo = leave_one_out_moran(units, y.to_numpy(), "queen", 999, seed)
        res.table("T11_moran_dejando_una_fuera_queen", loo)
        ok = loo.dropna(subset=["I"])
        res.set("espacial.loo_queen", {"I_min": float(ok.I.min()), "I_max": float(ok.I.max()),
                                       "significativos_p_bilateral_<0.05":
                                           ok.loc[ok.p_bilateral < 0.05, "EXCLUIDA"].tolist(),
                                       "no_calculables": loo.loc[loo.I.isna(), "EXCLUIDA"].tolist()})

        g = units.merge(rates["2019_2025"][["DPTO_KEY", "TASA_10K_EXPOSICION_OBSERVADA"]], on="DPTO_KEY")
        study_area_map(units, res.figures, "Fig_area_estudio")
        choropleth(g, "TASA_10K_EXPOSICION_OBSERVADA", res.figures, "Fig_mapa_tasa",
                   "Reports per 10,000 person-years")
        gi_map(units, local["queen"], res.figures, "Fig_mapa_Gi_FDR_queen")
    print(moran[["periodo", "pesos", "variable", "I", "p_bilateral"]].round(4).to_string(index=False))
    for wn, loc in local.items():
        print(f"\n[{wn}] Gi* transform={res.data['espacial']['local'][wn]['gi_transform']}")
        cols = ["DPTO_KEY", "VALOR", "k_vecinos", "Gi_z", "p_bilateral", "q_FDR", "q_BY",
                "Gi_clase_sin_ajuste", "Gi_clase_FDR", "LISA_cuadrante", "LISA_clase_FDR"]
        sig = loc[(loc.Gi_clase_sin_ajuste != "n.s.") | (loc.Gi_clase_FDR != "n.s.")]
        print(sig[cols].round(4).to_string(index=False) if len(sig) else "  sin unidades con p < 0,05")
        print(f"  no significables al 5 % (p mínimo > 0,05): "
              f"{res.data['espacial']['local'][wn]['unidades_no_significables_al_5pct']}")
    ctx.update(units=units, W=W, local=local)
    return ctx


def run_all(root):
    """Run every stage in order (about 30 min on a free Colab CPU)."""
    ctx = stage_init(root)
    for stage in (stage_data, stage_priority, stage_features, stage_k, stage_algorithms,
                  stage_audit, stage_temporal, stage_spatial, stage_multiverse,
                  stage_article_figures):
        ctx = stage(ctx)
    return ctx


# ---------------------------------------------------------------- stage 1b (v3.3)
def stage_priority(ctx):
    """Territories whose rate is higher than, lower than or not distinguishable from the rest of
    the country (main analysis and sensitivity analyses)."""
    plan, res, seed = ctx["plan"], ctx["res"], ctx["seed"]
    cfg = plan["prioridad"]
    with res.timer("1b_territorios_prioritarios"):
        specs = {"principal": cfg["principal"], **cfg["sensibilidades"]}
        tables, metas = {}, {}
        for name, sp in specs.items():
            t, meta = priority_table(ctx["panel"], sp["anios"], sp["exposicion"], B=cfg["bootstrap_B"],
                                     block=cfg["bloque_meses"], seed=seed, alpha=cfg["alpha"])
            tables[name], metas[name] = t, meta
            res.table("T14_territorios_prioritarios" if name == "principal"
                      else f"T14_territorios_prioritarios_{name}", t)
        summary = priority_summary(tables)
        main = tables["principal"]
        anual = annual_rr_table(ctx["panel"], cfg["principal"]["anios"], cfg["principal"]["exposicion"])
        res.table("T14b_razon_tasas_anual", anual)
        top5 = main.nlargest(5, "RR_VS_RESTO")["DPTO_KEY"].tolist()
        piv = anual.pivot(index="DPTO_KEY", columns="ANO", values="RR_VS_RESTO")
        res.set("prioridad", {"meta": metas, "resumen": summary,
                              "tabla_principal": records(main),
                              "rr_anual_rango_top5": [float(piv.loc[top5].min().min()),
                                                      float(piv.loc[top5].max().max())],
                              "conteo_clases": main["CLASE"].value_counts().to_dict()})
    cols = ["DPTO_KEY", "REPORTES", "CUOTA_REPORTES_PCT", "TASA_10K", "RR_VS_RESTO", "RR_IC95_INF",
            "RR_IC95_SUP", "q_FDR", "CLASE", "ANIOS_SOBRE_RESTO"]
    print(main[cols].round(3).to_string(index=False))
    for name, s in summary.items():
        print(f"{name}: {len(s['superior'])} superiores, {len(s['inferior'])} inferiores, "
              f"coincidencia con el principal {s['coincidencia_con_principal']:.0%}")
    ctx.update(priority=tables)
    return ctx


# ---------------------------------------------------------------- stage 9 (v3.3)
def stage_article_figures(ctx):
    """Manuscript Figs. 1-5 in Spanish (internal review) and English (submission)."""
    from .article_figures import build_all
    res = ctx["res"]
    with res.timer("9_figuras_articulo"):
        out = res.root / "figures_article"
        files = build_all(res.tables, ctx["units"], res.data["seleccion_k"]["K_elegido"], out)
        res.set("figuras_articulo", {"carpeta": "results/figures_article", "archivos": files})
    print("\n".join(files))
    return ctx


# ---------------------------------------------------------------- stage 8 (multiverse)
MANUSCRITO_REPORTADO = {"M1": {"K": 3, "silhouette": 0.5503},
                        "M2": {"moran_I": 0.330, "p": 0.002}}


def stage_multiverse(ctx):
    """Specification multiverse M1 (clustering) and M2 (spatial), with claim support and
    decision importance; the baseline specification is the reproduction anchor."""
    from .figures import specification_curve
    from .multiverse import claim_support, decision_importance, run_m1, run_m2
    plan, res, seed = ctx["plan"], ctx["res"], ctx["seed"]
    with res.timer("8_multiverso_M1"):
        m1, ktab = run_m1(ctx["df"], ctx["pop"], plan, seed)
        res.table("T12_multiverso_M1_especificaciones", m1)
        res.table("T12b_multiverso_M1_tablas_K", ktab)
        f1 = ["unidad", "winsor", "espacio", "escalador", "regla_k"]
        claims1 = ["afirma_estructura_por_silhouette", "afirma_estructura_por_filas",
                   "estructura_robusta_panel", "fuga_identidad"]
        bal = m1[m1["espacio"] != "O_manuscrito"]
        imp1 = pd.concat([decision_importance(bal, o, f1)
                          for o in ("silhouette", "NMI_unidad", "ari_bloque_temporal", "ari_fila")])
        sup1 = claim_support(m1, claims1)
        sup1f = pd.concat([claim_support(m1, claims1, by=f).rename(columns={f: "nivel"})
                           .assign(decision=f) for f in f1], ignore_index=True)
        res.table("T12c_M1_importancia_decisiones", imp1)
        res.table("T12d_M1_soporte_afirmaciones", sup1)
        res.table("T12e_M1_soporte_por_decision", sup1f)
        anc = m1[m1["es_manuscrito_original"]].iloc[0].to_dict()
        res.set("multiverso.M1", {"especificaciones": int(len(m1)),
                                  "ancla_manuscrito": anc,
                                  "manuscrito_reportado": MANUSCRITO_REPORTADO["M1"],
                                  "soporte": records(sup1), "importancia": records(imp1)})
        specification_curve(m1, "silhouette", f1, "estructura_robusta_panel",
                            "es_manuscrito_original", res.figures, "Fig_multiverso_M1_silhouette",
                            "Silhouette at selected K", hline=plan["multiverso"]["m1"]["umbral_silhouette"])
        specification_curve(m1, "NMI_unidad", f1, "fuga_identidad", "es_manuscrito_original",
                            res.figures, "Fig_multiverso_M1_NMI", "NMI(cluster, territorial unit)")
    with res.timer("8_multiverso_M2"):
        m2 = run_m2(ctx["df"], ctx["pop"], ctx["units"], plan, seed)
        res.table("T13_multiverso_M2_especificaciones", m2)
        f2 = ["winsor", "periodo", "variable", "pesos", "tipo_p", "correccion_local"]
        m2["sur_andino_detectado"] = m2["sur_andino_hotspots"] >= 1
        tasa = m2[m2["variable"] != "conteo"]
        claims2 = ["moran_significativo", "sur_andino_detectado", "lima_hotspot"]
        sup2 = pd.concat([claim_support(tasa, claims2).assign(subconjunto="tasas"),
                          claim_support(m2[m2["variable"] == "conteo"], claims2)
                          .assign(subconjunto="conteos")], ignore_index=True)
        sup2f = pd.concat([claim_support(tasa, claims2, by=f).rename(columns={f: "nivel"})
                           .assign(decision=f) for f in f2 if f != "variable"], ignore_index=True)
        glob = tasa.drop_duplicates(["winsor", "periodo", "variable", "pesos", "tipo_p"])
        imp2 = pd.concat([decision_importance(glob, "moran_I", ["winsor", "periodo", "variable", "pesos"]),
                          decision_importance(tasa, "n_hotspots", f2)])
        res.table("T13b_M2_soporte_afirmaciones", sup2)
        res.table("T13c_M2_soporte_por_decision", sup2f)
        res.table("T13d_M2_importancia_decisiones", imp2)
        anc = m2[m2["es_manuscrito_original"]].iloc[0].to_dict()
        res.set("multiverso.M2", {"especificaciones": int(len(m2)),
                                  "ancla_manuscrito": anc,
                                  "manuscrito_reportado": MANUSCRITO_REPORTADO["M2"],
                                  "soporte": records(sup2), "importancia": records(imp2)})
        g = glob.assign(sig_bilateral=lambda d: d["tipo_p"].eq("bilateral") & d["moran_significativo"])
        g = g[g["tipo_p"] == "bilateral"]
        specification_curve(g.assign(es_manuscrito_original=g["pesos"].eq("knn5_grados_manuscrito")
                                     & g["winsor"] & g["periodo"].eq("2019_2025")
                                     & g["variable"].eq("tasa_exposicion_total")),
                            "moran_I", ["winsor", "periodo", "variable", "pesos"], "sig_bilateral",
                            "es_manuscrito_original", res.figures, "Fig_multiverso_M2_Moran",
                            "Global Moran's I (rates)")
    a1, a2 = res.data["multiverso"]["M1"]["ancla_manuscrito"], res.data["multiverso"]["M2"]["ancla_manuscrito"]
    print(f"M1: {len(m1)} especificaciones | ancla manuscrito: K={a1['K']} silhouette={a1['silhouette']:.4f} "
          f"(reportado K=3, 0,5503) | ARI filas {a1['ari_fila']:.3f} vs bloques {a1['ari_bloque_temporal']:.3f} "
          f"| NMI {a1['NMI_unidad']:.3f}")
    print(sup1.round(3).to_string(index=False))
    print(imp1.round(3).to_string(index=False))
    print(f"\nM2: {len(m2)} especificaciones | ancla manuscrito: I={a2['moran_I']:.3f} p={a2['p_global']:.4f} "
          f"hotspots=[{a2['hotspots']}] (reportado I=0,330; p=0,002)")
    print(sup2.round(3).to_string(index=False))
    print(imp2.round(3).to_string(index=False))
    return ctx
