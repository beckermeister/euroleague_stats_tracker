
from bs4 import BeautifulSoup as bs
from os import path
import polars as pl
import pendulum
import platform
import requests
import tqdm
import time
import sys
import re
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.by import By

driver = None

if platform.system() == "Windows":
    from webdriver_manager.firefox import GeckoDriverManager
    driver = webdriver.Firefox(service=Service(GeckoDriverManager().install()))
if platform.system() == "Linux":
    from webdriver_manager.chrome import ChromeDriverManager
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )


def assert_round(driver, season, round):
    elm = driver.find_elements(
        By.CLASS_NAME, "game-center-select-shared_selectedValue__4xru_"
    )
    corr_season = False
    corr_round = False
    for s in elm:
        if s.get_attribute("aria-labelledby") == "prefix_seasons_select":
            corr_season = s.text == season
        elif s.get_attribute("aria-labelledby") == "prefix_rounds_select":
            corr_round = s.text == round
    return corr_round & corr_season


def load_with_selenium(season: str):
    links = []
    # Accept cookies
    eu_url = "https://www.euroleaguebasketball.net/euroleague/"

    driver.get(eu_url)
    delay = 10
    element = (
        WebDriverWait(driver, delay)
        .until(lambda x: x.find_element(By.ID, "onetrust-accept-btn-handler"))
    )
    element.click()

    driver.get("https://www.euroleaguebasketball.net/euroleague/game-center/")
    date_element = (
        WebDriverWait(driver, delay)
        .until(lambda x: x.find_element(
                By.CLASS_NAME,
                "game-center-group_groupTitle__5RCk4"
            )
        )
    )
    old_date = date_element.text
    season_name = f"{season}-{int(season[-2:]) + 1}"
    for round in tqdm.tqdm(range(1, 35)):
        entry_url = (
            "https://www.euroleaguebasketball.net/euroleague/game-center/?"
            f"round={round}&season=E{season}"
        )
        driver.get(entry_url)
        while not assert_round(
            driver, season_name, f"Round {round}"
        ):
            time.sleep(1)

        while not old_date != driver.find_element(
            By.CLASS_NAME, "game-center-group_groupTitle__5RCk4"
        ).text:
            time.sleep(1)

        body = driver.find_element(By.TAG_NAME, "body")

        body_content = body.get_attribute("innerHTML")

        soup = bs(body_content, "html.parser")

        for link in soup.find_all("a"):
            links.append(link.get("href"))

    driver.close()
    link_format = (
        r"/euroleague/game-center/\d\d\d\d-\d\d/[\w-]+/E\d\d\d\d/[\d]{1,3}/"
    )
    r = re.compile(link_format)
    newlist = list(filter(r.match, links))

    return list(dict.fromkeys(newlist))


def player_column_dicts(
        player_names: list,
        box1_columns: list,
        box2_columns: list,
        soup: bs
) -> tuple[dict[str, str], dict[str, str]]:
    div_class = (
        "game-box-scores-table-grouped-tab_tableGroupedRowsContainer__rmPnn "
        "game-box-scores-table-grid-sizing_tableGridSizing__KbFAw"
    )
    name_div = soup.find_all("div", attrs={"class": div_class})

    # Get amount of player name divs and divs themselves for home and away
    home_team_players = name_div[0].find_all("div", recursive=False)[2:]
    home_team_player_count = len(home_team_players)
    away_team_players = name_div[1].find_all("div", recursive=False)[2:]
    away_team_player_count = len(away_team_players)

    # Check if second last item contains Team, if it does there are 2 extra
    # rows, else only the total so one extra row
    # this is important for taking the appropriate amount of players
    # from the list
    # TODO: Take player names here directly, like why the extra steps
    if home_team_players[-2].find("b").get_text().strip() == "Team":
        home_team_player_count -= 2
        home_team_team = True
    else:
        home_team_player_count -= 1
        home_team_team = False
    if away_team_players[-2].find("b").get_text().strip() == "Team":
        away_team_player_count -= 2
        away_team_team = True
    else:
        away_team_player_count -= 1
        away_team_team = False

    t1_names = player_names[:home_team_player_count]
    t2_names = player_names[home_team_player_count:]

    t1_renames = {}
    for i, x in enumerate(t1_names):
        t1_renames[f"column_{i}"] = x[1]
    if home_team_team:
        t1_renames[f"column_{i+1}"] = "Team"
        t1_renames[f"column_{i+2}"] = "Total"
    else:
        t1_renames[f"column_{i+1}"] = "Total"

    t2_renames = {}
    for j, x in enumerate(t2_names):
        t2_renames[f"column_{j}"] = x[1]
    if away_team_team:
        t2_renames[f"column_{j+1}"] = "Team"
        t2_renames[f"column_{j+2}"] = "Total"
    else:
        t2_renames[f"column_{j+1}"] = "Total"

    return t1_renames, t2_renames


def get_game_info(soup: bs) -> dict:
    """Takes a game page and returns relevant data like team names, Date and
    Time and Round

    Args:
        soup (bs): BeatifoulSoup4 Object with parsed html

    Returns:
        dict: dict with contents home_team, away_team, round, date, time
    """
    name_class = "club-info_name__xB4rz"
    team_names = []
    for element in soup.find_all("h1", attrs={"class": name_class}):
        team_names.append(element.get_text().strip())

    game_info_class = "event-info_listItem__Iu4ou"
    game_info = []
    for element in soup.find_all("li", attrs={"class": game_info_class}):
        game_info.append(element.get_text().strip())

    return {
        "home_team": team_names[0],
        "away_team": team_names[1],
        "round": re.search(r"(\d{1,2})", game_info[0])[0],
        "date": pendulum.from_format(game_info[1], "D MMM YYYY"),
        "time": game_info[3]
    }


def get_game_data(link: str) -> pl.DataFrame:
    """Pulls game data for game under specified link from euroleague homepage

    Args:
        link (str): euroleague page game link

    Returns:
        pl.DataFrame: DataFrame with all relevant Data From Site
    """

    base_url = f"https://www.euroleaguebasketball.net{link}"
    site = requests.get(base_url)

    # Open Parser
    soup = bs(str(site.content), 'html.parser')
    # Class names for relevant Parts of HTML
    columns_class = (
        "game-box-scores-table-grouped-column_"
        "tableGroupedColumnStatGroupContainer__Oci84"
    )
    row_class = (
        "game-box-scores-table-grouped-column_"
        "tableGroupedRowStatGroupContainer__wluIz"
    )
    stat_name_class = (
        "game-box-scores-table-grouped-"
        "column_groupedTableHeading__XTxR_"
    )
    stat_cell_class = (
        "game-box-scores-table-grouped-column_tableStatCell__4zJlJ"
    )

    # Class for Player link, regex the name of the Player
    player_link = "game-box-scores-table-grouped-tab_playerLink__MqVrl"
    re_player = r"/euroleague/players/([\w-]+)/[\d\w]+/"
    players = []
    for link in soup.find_all("a", attrs={"class": player_link}):
        players.append((
            link.get("href"), re.match(re_player, link.get("href")).groups()[0]
        ))

    # Find all the Data Columns for a Team
    # Save them in List of Columns to be appended later
    stats_collection = []
    for element in soup.find_all("div", attrs={"class": columns_class}):
        col_stats = []
        col_heads = [
            stathead.text for stathead in element.find_all(
                "div", attrs={"class": stat_name_class}
            )
        ]
        for row in element.find_all("div", attrs={"class": row_class}):
            stats = row.find_all("div", attrs={"class": stat_cell_class})
            if stats:
                col_stats.append([stat.text for stat in stats])
        schema = {}
        for i in col_heads:
            schema["i"]: str
        stats_df = pl.DataFrame(data=col_stats, schema=schema)
        stats_collection.append(stats_df)

    if len(stats_collection) == 0:
        return None
    boxscore_t1 = pl.concat(stats_collection[:9])
    boxscore_t2 = pl.concat(stats_collection[9:])

    # TODO: Maybe put in seperate File for ease of reading
    stat_names = pl.Series(values=[
        "Minutes", "Points",
        "2P_Made/Attempted", "2P_Percentage",
        "3P_Made/Attempted", "3P_Percentage",
        "FTP_Made/Attempted", "FTP_Percentage",
        "O_Rebounds", "D_Rebounds", "Total_Rebounds",
        "Assists", "Steals", "Turnovers",
        "Blocks", "ReceivedBlocks",
        "FoulsCommited", "FoulReceived",
        "Effectivity", "PlusMinus"
    ], name="Stat")

    game_info = get_game_info(soup)

    home_names, away_names = player_column_dicts(
        players, boxscore_t1.columns, boxscore_t2.columns, soup
    )
    boxscore_t1 = (
        boxscore_t1
        .rename(home_names)  # add player names to as column names
        .with_columns(stat_names)  # add stat names to rows
        .transpose(  # Pivot Boxscore to have player names as data Entry
            include_header=True,
            header_name="Player",
            column_names="Stat"
        )
        .with_columns(
            pl.lit(game_info["home_team"]).alias("Team"),
            pl.lit(game_info["away_team"]).alias("Opponent"),
            pl.lit(True).alias("Home")
        )
    )
    boxscore_t2 = (
        boxscore_t2
        .rename(away_names)
        .with_columns(stat_names)
        .transpose(
            include_header=True,
            header_name="Player",
            column_names="Stat"
        )
        .with_columns(
            pl.lit(game_info["away_team"]).alias("Team"),
            pl.lit(game_info["home_team"]).alias("Opponent"),
            pl.lit(False).alias("Home")
        )
    )
    boxscore: pl.DataFrame = pl.concat([boxscore_t1, boxscore_t2])
    percent_format = r"([\d.]+)"
    # Do all the Type conversions to String, float, etc
    boxscore = (
        boxscore
        .filter(pl.col("Player").ne("Team"))
        .with_columns(
            pl.col("Minutes").str
            .extract_groups(r"(?P<Minutes>\d+):(?P<Seconds>\d+)"),
            pl.col("Points").cast(pl.Int16),
            pl.col("2P_Made/Attempted").str.extract_groups(
                r"(?P<TwoPMakes>\d{1,2})/(?P<TwoPAttempts>\d{1,2})"
            ),
            pl.col("3P_Made/Attempted").str.extract_groups(
                r"(?P<ThreePMakes>\d{1,2})/(?P<ThreePAttempts>\d{1,2})"
            ),
            pl.col("FTP_Made/Attempted").str.extract_groups(
                r"(?P<FTMakes>\d{1,2})/(?P<FTAttempts>\d{1,2})"
            ),
            pl.col("2P_Percentage").str.extract(percent_format, 1)
            .cast(pl.Float32).truediv(100),
            pl.col("3P_Percentage").str.extract(percent_format, 1)
            .cast(pl.Float32).truediv(100),
            pl.col("FTP_Percentage").str.extract(percent_format, 1)
            .cast(pl.Float32).truediv(100),
            pl.col("O_Rebounds").cast(pl.Int16),
            pl.col("D_Rebounds").cast(pl.Int16),
            pl.col("Total_Rebounds").cast(pl.Int16),
            pl.col('Assists').cast(pl.Int16),
            pl.col('Steals').cast(pl.Int16),
            pl.col('Turnovers').cast(pl.Int16),
            pl.col('Blocks').cast(pl.Int16),
            pl.col('ReceivedBlocks').cast(pl.Int16),
            pl.col('FoulsCommited').cast(pl.Int16),
            pl.col('FoulReceived').cast(pl.Int16),
            pl.col('Effectivity').cast(pl.Int16),
            pl.when(pl.col("PlusMinus") == "")
            .then(pl.lit("0"))
            .otherwise(pl.col("PlusMinus"))
            .cast(pl.Int16).alias("PlusMinus")
        )
        .unnest([
            "2P_Made/Attempted", "3P_Made/Attempted",
            "FTP_Made/Attempted", "Minutes"
        ])
        .with_columns(
            Seconds=(
                pl.col("Minutes")
                .cast(pl.Int64)
                .mul(60)
                .add(pl.col("Seconds")
                     .cast(pl.Int64))
            ),
            Date=pl.lit(game_info["date"]),
            Round=pl.lit(game_info["round"]),
            GameTime=pl.lit(game_info["time"])
        )
        .drop("Minutes")
    )

    return boxscore


def get_season_data(season: str):
    res = load_with_selenium(season)
    print(len(res))
    boxscores = []
    for link in tqdm.tqdm(res):
        game_data = get_game_data(link)
        if game_data is not None:
            boxscores.append(game_data)
        time.sleep(1.5)

    all_stats: pl.DataFrame = pl.concat(boxscores).rechunk()

    all_stats.shape
    print(all_stats.schema)

    team_totals = (
        all_stats
        .filter(pl.col("Player").eq("Total"))
        .sort("Date")
        .with_columns(
            pl.col("Round").cast(pl.Int16),
            pl.col("TwoPMakes").cast(pl.Int16),
            pl.col("TwoPAttempts").cast(pl.Int16),
            pl.col("ThreePMakes").cast(pl.Int16),
            pl.col("ThreePAttempts").cast(pl.Int16),
            pl.col("FTMakes").cast(pl.Int16),
            pl.col("FTAttempts").cast(pl.Int16),
            game_number=pl.col("Player").cum_count().over("Team")
        )
        .select(
            avg_points=pl.col('Points').cum_sum().over("Team").truediv("game_number"),
            avg_TwoPMakes=pl.col("TwoPMakes").cum_sum().over("Team").truediv("game_number"),
            avg_TwoPAttempts=pl.col("TwoPAttempts").cum_sum().over("Team").truediv("game_number"),
            avg_2P_Percentage=pl.col("2P_Percentage").cum_sum().over("Team").truediv("game_number"),
            avg_ThreePMakes=pl.col("ThreePMakes").cum_sum().over("Team").truediv("game_number"),
            avg_ThreePAttempts=pl.col("ThreePAttempts").cum_sum().over("Team").truediv("game_number"),
            avg_3P_Percentage=pl.col("3P_Percentage").cum_sum().over("Team").truediv("game_number"),
            avg_FTMakes=pl.col("FTMakes").cum_sum().over("Team").truediv("game_number"),
            avg_FTAttempts=pl.col("FTAttempts").cum_sum().over("Team").truediv("game_number"),
            avg_FTP_Percentage=pl.col("FTP_Percentage").cum_sum().over("Team").truediv("game_number"),
            avg_O_Rebounds=pl.col("O_Rebounds").cum_sum().over("Team").truediv("game_number"),
            avg_D_Rebounds=pl.col("D_Rebounds").cum_sum().over("Team").truediv("game_number"),
            avg_Total_Rebounds=pl.col("Total_Rebounds").cum_sum().over("Team").truediv("game_number"),
            avg_Assists=pl.col("Assists").cum_sum().over("Team").truediv("game_number"),
            avg_Steals=pl.col("Steals").cum_sum().over("Team").truediv("game_number"),
            avg_Turnovers=pl.col("Turnovers").cum_sum().over("Team").truediv("game_number"),
            avg_Blocks=pl.col("Blocks").cum_sum().over("Team").truediv("game_number"),
            avg_ReceivedBlocks=pl.col("ReceivedBlocks").cum_sum().over("Team").truediv("game_number"),
            avg_FoulsCommited=pl.col("FoulsCommited").cum_sum().over("Team").truediv("game_number"),
            avg_FoulReceived=pl.col("FoulReceived").cum_sum().over("Team").truediv("game_number"),
            avg_Effectivity=pl.col("Effectivity").cum_sum().over("Team").truediv("game_number"),
            avg_PlusMinus=pl.col("PlusMinus").cum_sum().over("Team").truediv("game_number"),
            game_number=pl.col("game_number"),
            Team=pl.col("Team"),
            Player=pl.col("Player"),
            Round=pl.col("Round")
        )
    )

    stats_with_running_averages = (
        all_stats
        .filter(pl.col("Player").ne("Total"))
        .sort("Date")
        .with_columns(
            pl.col("Round").cast(pl.Int16),
            pl.col("TwoPMakes").cast(pl.Int16),
            pl.col("TwoPAttempts").cast(pl.Int16),
            pl.col("ThreePMakes").cast(pl.Int16),
            pl.col("ThreePAttempts").cast(pl.Int16),
            pl.col("FTMakes").cast(pl.Int16),
            pl.col("FTAttempts").cast(pl.Int16),
            game_number=pl.col("Player").cum_count().over("Player")
        )
        .with_columns(
            avg_seconds=pl.col("Seconds").cum_sum().over("Player").truediv("game_number"),
            avg_points=pl.col('Points').cum_sum().over("Player").truediv("game_number"),
            avg_TwoPMakes=pl.col("TwoPMakes").cum_sum().over("Player").truediv("game_number"),
            avg_TwoPAttempts=pl.col("TwoPAttempts").cum_sum().over("Player").truediv("game_number"),
            avg_2P_Percentage=pl.col("2P_Percentage").cum_sum().over("Player").truediv("game_number"),
            avg_ThreePMakes=pl.col("ThreePMakes").cum_sum().over("Player").truediv("game_number"),
            avg_ThreePAttempts=pl.col("ThreePAttempts").cum_sum().over("Player").truediv("game_number"),
            avg_3P_Percentage=pl.col("3P_Percentage").cum_sum().over("Player").truediv("game_number"),
            avg_FTMakes=pl.col("FTMakes").cum_sum().over("Player").truediv("game_number"),
            avg_FTAttempts=pl.col("FTAttempts").cum_sum().over("Player").truediv("game_number"),
            avg_FTP_Percentage=pl.col("FTP_Percentage").cum_sum().over("Player").truediv("game_number"),
            avg_O_Rebounds=pl.col("O_Rebounds").cum_sum().over("Player").truediv("game_number"),
            avg_D_Rebounds=pl.col("D_Rebounds").cum_sum().over("Player").truediv("game_number"),
            avg_Total_Rebounds=pl.col("Total_Rebounds").cum_sum().over("Player").truediv("game_number"),
            avg_Assists=pl.col("Assists").cum_sum().over("Player").truediv("game_number"),
            avg_Steals=pl.col("Steals").cum_sum().over("Player").truediv("game_number"),
            avg_Turnovers=pl.col("Turnovers").cum_sum().over("Player").truediv("game_number"),
            avg_Blocks=pl.col("Blocks").cum_sum().over("Player").truediv("game_number"),
            avg_ReceivedBlocks=pl.col("ReceivedBlocks").cum_sum().over("Player").truediv("game_number"),
            avg_FoulsCommited=pl.col("FoulsCommited").cum_sum().over("Player").truediv("game_number"),
            avg_FoulReceived=pl.col("FoulReceived").cum_sum().over("Player").truediv("game_number"),
            avg_Effectivity=pl.col("Effectivity").cum_sum().over("Player").truediv("game_number"),
            avg_PlusMinus=pl.col("PlusMinus").cum_sum().over("Player").truediv("game_number")
        )
    )

    for_merge_totals = (
        team_totals
        .filter(pl.col("Round").ne(34))
        .with_columns(
            team_round_shorthand=pl.concat_str(pl.col("Team"), pl.col("Round"))
        )
    )

    player_stats_for_merged = (
        stats_with_running_averages
        .with_columns(
            pl.col("Round").sub(1).alias("merge_round")
        )
        .with_columns(
            pl.when(pl.col("merge_round") == 0)
            .then(1)
            .otherwise(pl.col("merge_round"))
            .alias("merge_round")
        )
        .with_columns(
            team_round_shorthand_own=pl.concat_str(
                pl.col("Team"),
                pl.col("merge_round")
            ),
            team_round_shorthand_opponent=pl.concat_str(
                pl.col("Opponent"),
                pl.col("merge_round")
            )
        )
    )

    merged_stats = (
        player_stats_for_merged
        .join(
            for_merge_totals,
            left_on="team_round_shorthand_own",
            right_on="team_round_shorthand",
            suffix="_own_team"
        )
        .join(
            for_merge_totals,
            left_on="team_round_shorthand_opponent",
            right_on="team_round_shorthand",
            suffix="_opponent"
        )
        .select(
            pl.exclude([
                "team_round_shorthand_own", "team_round_shorthand_opponent",
                "game_number_own_team", "Team_own_team", "Player_own_team",
                "Round_own_team", "game_number_opponent", "Team_opponent",
                "Player_opponent", "Round_opponent"
            ])
        )
    )
    season_num = int(season)
    season_name = f"{season_num-2000}_{season_num-1999}"
    team_stats_path = path.join(
        ".", "data", "external", f"Team stats_{season_name}.xlsx"
    )
    stats_df = pl.read_excel(
        team_stats_path, sheet_name="stats_clean", engine="xlsx2csv"
    )

    prepared_team_stats = (
        stats_df
        .filter(pl.col("TEAM").is_not_null())
        .select([
            "TEAM", "PACE", "POSS", "OFF RTG",	"DEF RTG",	"NET RTG", "OR%",
            "DR%", "TR%", "AST%", "AST Ratio", "AST/TO", "TO Ratio", "ST%",
            "PF 100 Poss", "DF 100 Poss", "BLK%"
        ])
        .with_columns(
            pl.col("ST%").truediv(100),
            pl.col("BLK%").truediv(100),
        )
    )

    full_stats = (
        merged_stats
        .join(
            prepared_team_stats,
            left_on="Team",
            right_on="TEAM",
            suffix="_own_team"
        )
        .join(
            prepared_team_stats,
            left_on="Opponent",
            right_on="TEAM",
            suffix="_opponent"
        )
        .with_columns(
            Season=pl.lit(season_name)
        )
    )
    return full_stats


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Only run with Season starting year specified")
        exit()
    season = sys.argv[1]
    stats = get_season_data(season)
    print(stats.head())
    stats.write_parquet(f"./data/processed/season_{season}.pq")
