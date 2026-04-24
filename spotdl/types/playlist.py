"""
Playlist module for retrieving playlist data from Spotify.
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from spotdl.types.song import Song, SongList
from spotdl.utils.spotify import SpotifyClient

__all__ = ["Playlist", "PlaylistError"]

logger = logging.getLogger(__name__)

_ALBUM_BATCH_SIZE = 20  # Spotify albums endpoint maximum
_ARTIST_BATCH_SIZE = 50  # Spotify artists endpoint maximum


class PlaylistError(Exception):
    """
    Base class for all exceptions related to playlists.
    """


@dataclass(frozen=True)
class Playlist(SongList):
    """
    Playlist class for retrieving playlist data from Spotify.
    """

    description: str
    author_url: str
    author_name: str
    cover_url: str

    @staticmethod
    def get_metadata(url: str) -> Tuple[Dict[str, Any], List[Song]]:
        """
        Get metadata for a playlist.

        ### Arguments
        - url: The URL of the playlist.

        ### Returns
        - A dictionary with metadata.
        """

        spotify_client = SpotifyClient()

        playlist = spotify_client.playlist(url)
        if playlist is None:
            raise PlaylistError("Invalid playlist URL.")

        metadata = {
            "name": playlist["name"],
            "url": url,
            "description": playlist["description"],
            "author_url": playlist["external_urls"]["spotify"],
            "author_name": playlist["owner"]["display_name"],
            "cover_url": (
                max(
                    playlist["images"],
                    key=lambda i: (
                        0
                        if i["width"] is None or i["height"] is None
                        else i["width"] * i["height"]
                    ),
                )["url"]
                if (playlist.get("images") is not None and len(playlist["images"]) > 0)
                else ""
            ),
        }

        playlist_response = spotify_client.playlist_items(url)
        if playlist_response is None:
            raise PlaylistError(f"Wrong playlist id: {url}")

        # Collect all track items (paginated)
        tracks = playlist_response["items"]
        while playlist_response["next"]:
            playlist_response = spotify_client.next(playlist_response)

            if playlist_response is None:
                break

            tracks.extend(playlist_response["items"])

        # Filter to valid, non-local tracks and record which album/artist IDs we need
        valid_tracks = []
        seen_album_ids: List[str] = []
        seen_artist_ids: List[str] = []

        for track in tracks:
            if not isinstance(track, dict) or track.get("track") is None:
                continue

            track_meta = track["track"]

            if track_meta.get("is_local") or track_meta.get("type") != "track":
                logger.warning(
                    "Skipping track: %s local tracks and %s are not supported",
                    track_meta.get("id"),
                    track_meta.get("type"),
                )
                continue

            track_id = track_meta.get("id")
            if track_id is None or track_meta.get("duration_ms") == 0:
                continue

            valid_tracks.append(track_meta)

            album_id = track_meta.get("album", {}).get("id")
            if album_id and album_id not in seen_album_ids:
                seen_album_ids.append(album_id)

            primary_artist_id = (track_meta.get("artists") or [{}])[0].get("id")
            if primary_artist_id and primary_artist_id not in seen_artist_ids:
                seen_artist_ids.append(primary_artist_id)

        # Batch-fetch full album objects (genres, label, copyrights, disc count)
        album_data: Dict[str, Any] = {}
        for i in range(0, len(seen_album_ids), _ALBUM_BATCH_SIZE):
            batch = seen_album_ids[i : i + _ALBUM_BATCH_SIZE]
            result = spotify_client.albums(batch)
            if result:
                for album in result["albums"]:
                    if album:
                        album_data[album["id"]] = album

        # Batch-fetch full artist objects (genres)
        artist_data: Dict[str, Any] = {}
        for i in range(0, len(seen_artist_ids), _ARTIST_BATCH_SIZE):
            batch = seen_artist_ids[i : i + _ARTIST_BATCH_SIZE]
            result = spotify_client.artists(batch)
            if result:
                for artist in result["artists"]:
                    if artist:
                        artist_data[artist["id"]] = artist

        # Build fully-populated Song objects from the combined data
        songs = []
        for track_no, track_meta in enumerate(valid_tracks):
            album_meta = track_meta.get("album", {})
            album_id = album_meta.get("id")
            full_album = album_data.get(album_id, {})

            primary_artist_id = (track_meta.get("artists") or [{}])[0].get("id")
            full_artist = artist_data.get(primary_artist_id, {})

            release_date = album_meta.get("release_date")
            artists = [artist["name"] for artist in track_meta.get("artists", [])]

            genres = (full_album.get("genres") or []) + (
                full_artist.get("genres") or []
            )

            # disc_count is the disc number of the last track in the album
            disc_count = None
            album_tracks = full_album.get("tracks", {}).get("items")
            if album_tracks:
                disc_count = int(album_tracks[-1]["disc_number"])

            song = Song.from_missing_data(
                name=track_meta["name"],
                artists=artists,
                artist=artists[0] if artists else None,
                artist_id=primary_artist_id,
                album_id=album_id,
                album_name=album_meta.get("name"),
                album_artist=(
                    album_meta.get("artists", [])[0]["name"]
                    if album_meta.get("artists")
                    else None
                ),
                album_type=album_meta.get("album_type"),
                disc_number=track_meta["disc_number"],
                disc_count=disc_count,
                duration=int(track_meta["duration_ms"] / 1000),
                year=release_date[:4] if release_date else None,
                date=release_date,
                track_number=track_meta["track_number"],
                tracks_count=album_meta.get("total_tracks"),
                song_id=track_meta["id"],
                explicit=track_meta["explicit"],
                url=track_meta["external_urls"]["spotify"],
                isrc=track_meta.get("external_ids", {}).get("isrc"),
                cover_url=(
                    max(album_meta["images"], key=lambda i: i["width"] * i["height"])[
                        "url"
                    ]
                    if len(album_meta.get("images", [])) > 0
                    else None
                ),
                genres=genres if genres else None,
                publisher=full_album.get("label") or None,
                copyright_text=(
                    full_album["copyrights"][0]["text"]
                    if full_album.get("copyrights")
                    else None
                ),
                popularity=track_meta.get("popularity"),
                list_position=track_no + 1,
            )

            songs.append(song)

        return metadata, songs
