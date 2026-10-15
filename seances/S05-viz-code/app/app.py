"""
Application d'analyse NYC Taxi — S05.

Lancement :   docker compose --profile app up -d --build
Adresse :     http://localhost:8501
"""
import json
import os
import math

import pandas as pd
import plotly.express as px
import sqlalchemy
import streamlit as st

st.set_page_config(page_title="NYC Taxi — analyse", layout="wide")

PG = (f"postgresql+psycopg2://{os.getenv('PG_USER', 'cours')}:{os.getenv('PG_PASSWORD', 'cours')}"
      f"@{os.getenv('PG_HOST', 'postgres')}:5432/{os.getenv('PG_DB', 'nyctaxi')}")
GEOJSON = os.getenv("ZONES_GEOJSON", "/data/zones.geojson")


# --- Données (mises en cache : lues une seule fois) ---------------------------
@st.cache_data(ttl=600)
def charger():
    moteur = sqlalchemy.create_engine(PG)
    horaires = pd.read_sql("SELECT * FROM gold_trajets_horaires", moteur)
    zones = pd.read_sql("SELECT * FROM gold_zones", moteur)
    horaires["heure"] = pd.to_datetime(horaires["heure_pickup"]).dt.hour
    horaires["jour_semaine"] = pd.to_datetime(horaires["heure_pickup"]).dt.dayofweek
    horaires["jour"] = pd.to_datetime(horaires["heure_pickup"]).dt.date
    return horaires, zones


@st.cache_data
def contours():
    if not os.path.exists(GEOJSON):
        return None
    with open(GEOJSON, encoding="utf-8") as f:
        return json.load(f)


horaires, zones = charger()
geo = contours()

# --- Filtres -------------------------------------------------------------------
st.sidebar.header("Filtres")
arrondissements = sorted(a for a in horaires["arrondissement"].dropna().unique() if a not in ("Unknown", "N/A"))
choix = st.sidebar.multiselect("Arrondissements", arrondissements, default=arrondissements)
plage = st.sidebar.slider("Heures de prise en charge", 0, 23, (0, 23))

# Exercice 1 : le lundi vaut 0, le dimanche vaut 6.
jours = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
jours_choisis = st.sidebar.multiselect("Jours de la semaine", jours, default=jours)
numeros_jours = [jours.index(jour) for jour in jours_choisis]

h = horaires[
    horaires["arrondissement"].isin(choix)
    & horaires["heure"].between(*plage)
    & horaires["jour_semaine"].isin(numeros_jours)
].copy()
z = zones[zones["arrondissement"].isin(choix)]

# --- Indicateurs -----------------------------------------------------------------
st.title("Où et quand les taxis gagnent-ils le plus ?")
k1, k2, k3, k4 = st.columns(4)
k1.metric("Courses", f"{int(h['courses'].sum()):,}".replace(",", " "))
k2.metric("Revenu total", f"{h['revenu'].sum() / 1e6:,.1f} M$")
k3.metric("Prix moyen", f"{(h['revenu'].sum() / max(h['courses'].sum(), 1)):.2f} $")
k4.metric("Pourboire moyen", f"{(h['pourboire_moyen'] * h['courses']).sum() / max(h['courses'].sum(), 1):.2f} $")

# --- Graphiques ----------------------------------------------------------------
g1, g2 = st.columns(2)

par_heure = h.groupby(["heure", "arrondissement"], as_index=False)["courses"].sum()
fig = px.line(par_heure, x="heure", y="courses", color="arrondissement", markers=True,
              labels={"heure": "Heure de prise en charge", "courses": "Courses (mois)"},
              title="Activité par heure")
g1.plotly_chart(fig, use_container_width=True)

top = z.nlargest(15, "courses").sort_values("courses")
fig = px.bar(top, x="courses", y="zone", color="arrondissement", orientation="h",
             labels={"courses": "Courses (mois)", "zone": ""}, title="Les 15 zones de départ les plus actives")
g2.plotly_chart(fig, use_container_width=True)

# Exercice 2 : pondérer chaque moyenne par son nombre de courses.
# Une ligne de gold_trajets_horaires représente déjà plusieurs courses.
valides = h.dropna(subset=["pourboire_moyen", "courses"])
pourboires = (
    valides.assign(total_pourboires=valides["pourboire_moyen"] * valides["courses"])
    .groupby("heure", as_index=False)[["total_pourboires", "courses"]].sum()
)
pourboires = pourboires[pourboires["courses"] > 0].copy()
pourboires["pourboire_moyen"] = pourboires["total_pourboires"] / pourboires["courses"]
if not pourboires.empty:
    pic = pourboires.loc[pourboires["pourboire_moyen"].idxmax(), "heure"]
    fig = px.line(
        pourboires, x="heure", y="pourboire_moyen", markers=True,
        labels={"heure": "Heure de prise en charge", "pourboire_moyen": "Pourboire moyen ($)"},
        title=f"Le pourboire moyen est maximal à {int(pic)} h dans la sélection",
    )
    fig.update_traces(hovertemplate="Heure : %{x} h<br>Pourboire moyen : %{y:.2f} $<extra></extra>")
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("Aucune donnée de pourboire pour cette sélection.")

st.caption("Le classement des zones et la carte portent sur le mois entier et suivent uniquement le filtre des arrondissements. La table gold_zones ne contient pas le détail par jour ou par heure.")

# Exercice 3 : Plotly reçoit une couleur transformée en log10(1 + courses).
# Le +1 permet de représenter aussi les zones avec zéro course.
z = z.copy()
z["log_courses"] = z["courses"].apply(lambda n: math.log10(1 + n))

if geo is not None:
    fig = px.choropleth_map(z, geojson=geo, locations="PULocationID", featureidkey="properties.LocationID",
                            color="log_courses", hover_name="zone",
                            hover_data={"courses": True, "prix_moyen": ":.2f", "PULocationID": False, "log_courses": False},
                            color_continuous_scale="Viridis", map_style="carto-positron",
                            center={"lat": 40.73, "lon": -73.94}, zoom=9.3, opacity=0.75,
                            labels={"log_courses": "log10(1 + courses)"}, title="Nombre de courses par zone de départ — échelle logarithmique")
    fig.update_layout(height=600, margin={"l": 0, "r": 0, "t": 40, "b": 0})
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("Carte indisponible : lancez d'abord le notebook 05a pour créer data/zones.geojson.")

with st.expander("Voir les données"):
    st.dataframe(z.sort_values("courses", ascending=False), use_container_width=True)
