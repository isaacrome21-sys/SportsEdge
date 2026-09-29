#!/usr/bin/env Rscript

# Extract only pre-target NFL rows from immutable nflverse archive RDS assets.
# Base R only: no network calls and no package dependencies.
args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 7) {
  stop("usage: extract_nflverse_prop_archive.R STATS_RDS SNAPS_RDS PLAYERS_RDS OUT_DIR SEASON TARGET_WEEK TEAMS_CSV")
}

stats_path <- args[[1]]
snaps_path <- args[[2]]
players_path <- args[[3]]
out_dir <- args[[4]]
season <- as.integer(args[[5]])
target_week <- as.integer(args[[6]])
teams <- strsplit(args[[7]], ",", fixed = TRUE)[[1]]
teams <- toupper(trimws(teams))

if (is.na(season) || is.na(target_week) || target_week < 1 || length(teams) < 1) {
  stop("invalid target arguments")
}
dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)

stats <- readRDS(stats_path)
snaps <- readRDS(snaps_path)
players <- readRDS(players_path)
if (!is.data.frame(stats) || !is.data.frame(snaps) || !is.data.frame(players)) {
  stop("archive assets must decode to data frames")
}

required <- function(df, names, label) {
  missing <- setdiff(names, colnames(df))
  if (length(missing)) stop(paste0(label, " missing columns: ", paste(missing, collapse = ",")))
}
required(stats, c("season", "week"), "stats")
required(snaps, c("season", "week"), "snaps")

team_col <- function(df, label) {
  choices <- c("recent_team", "team")
  hit <- choices[choices %in% colnames(df)]
  if (!length(hit)) stop(paste0(label, " missing team column"))
  hit[[1]]
}
stats_team <- team_col(stats, "stats")
snaps_team <- team_col(snaps, "snaps")

stats_keep <- stats$season == season & stats$week < target_week & toupper(as.character(stats[[stats_team]])) %in% teams
snaps_keep <- snaps$season == season & snaps$week < target_week & toupper(as.character(snaps[[snaps_team]])) %in% teams
stats_out <- stats[which(stats_keep %in% TRUE), , drop = FALSE]
snaps_out <- snaps[which(snaps_keep %in% TRUE), , drop = FALSE]

# Defensive proof: the extractor itself must never emit target-week/later rows.
if (nrow(stats_out) && any(stats_out$season > season | (stats_out$season == season & stats_out$week >= target_week))) {
  stop("stats PIT filter failed")
}
if (nrow(snaps_out) && any(snaps_out$season > season | (snaps_out$season == season & snaps_out$week >= target_week))) {
  stop("snap PIT filter failed")
}

# Crosswalk only the player identities touched by the extracted rows when known.
player_mask <- rep(FALSE, nrow(players))
if ("player_id" %in% colnames(stats_out) && "gsis_id" %in% colnames(players)) {
  player_mask <- player_mask | players$gsis_id %in% unique(stats_out$player_id)
}
snap_pfr_col <- c("pfr_player_id", "pfr_id")
snap_pfr_col <- snap_pfr_col[snap_pfr_col %in% colnames(snaps_out)]
players_pfr_col <- c("pfr_id", "pfr_player_id")
players_pfr_col <- players_pfr_col[players_pfr_col %in% colnames(players)]
if (length(snap_pfr_col) && length(players_pfr_col)) {
  player_mask <- player_mask | players[[players_pfr_col[[1]]]] %in% unique(snaps_out[[snap_pfr_col[[1]]]])
}
players_out <- players[which(player_mask %in% TRUE), , drop = FALSE]

write.csv(stats_out, file.path(out_dir, "stats_player_week_pre_target.csv"), row.names = FALSE, na = "")
write.csv(snaps_out, file.path(out_dir, "snap_counts_pre_target.csv"), row.names = FALSE, na = "")
write.csv(players_out, file.path(out_dir, "players_crosswalk.csv"), row.names = FALSE, na = "")

cat(sprintf("stats_rows=%d\n", nrow(stats_out)))
cat(sprintf("snap_rows=%d\n", nrow(snaps_out)))
cat(sprintf("player_rows=%d\n", nrow(players_out)))
