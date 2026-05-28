#define _GNU_SOURCE
#include <ctype.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

typedef struct {
    char *path;
    char *name;
    const char *source_folder;
    char stamp[16]; // YYYYMMDD_HHMMSS + '\0'
    time_t start;
    int is_event;
} Clip;

typedef struct {
    Clip *items;
    size_t len;
    size_t cap;
} ClipList;

typedef struct {
    char *body;
    size_t body_len;
    int max_index;
    int has_existing;
} ExistingJourneys;

static void die(const char *msg) {
    perror(msg);
    exit(1);
}

static char *xstrdup(const char *s) {
    size_t n = strlen(s);
    char *p = (char *)malloc(n + 1);
    if (!p) die("malloc");
    memcpy(p, s, n + 1);
    return p;
}

static void cliplist_push(ClipList *list, Clip c) {
    if (list->len == list->cap) {
        size_t new_cap = list->cap ? list->cap * 2 : 64;
        Clip *new_items = (Clip *)realloc(list->items, new_cap * sizeof(Clip));
        if (!new_items) die("realloc");
        list->items = new_items;
        list->cap = new_cap;
    }
    list->items[list->len++] = c;
}

static int ends_with_mp4(const char *name) {
    size_t n = strlen(name);
    if (n < 4) return 0;
    const char *ext = name + n - 4;
    return (tolower((unsigned char)ext[0]) == '.' &&
            tolower((unsigned char)ext[1]) == 'm' &&
            tolower((unsigned char)ext[2]) == 'p' &&
            tolower((unsigned char)ext[3]) == '4');
}

static time_t timegm_fallback(struct tm *tm) {
#ifdef __USE_BSD
    return timegm(tm);
#else
    return mktime(tm);
#endif
}

static int parse_stamp(const char *name, char stamp[16], time_t *out) {
    if (strlen(name) < 15) return 0;
    if (name[8] != '_') return 0;
    for (int i = 0; i < 15; i++) {
        if (i == 8) continue;
        if (!isdigit((unsigned char)name[i])) return 0;
    }
    memcpy(stamp, name, 15);
    stamp[15] = '\0';

    struct tm tm = {0};
    int year = 0;
    int mon = 0;
    int mday = 0;
    int hour = 0;
    int min = 0;
    int sec = 0;
    if (sscanf(stamp, "%4d%2d%2d_%2d%2d%2d", &year, &mon, &mday, &hour, &min, &sec) != 6) {
        return 0;
    }
    tm.tm_year = year - 1900;
    tm.tm_mon = mon - 1;
    tm.tm_mday = mday;
    tm.tm_hour = hour;
    tm.tm_min = min;
    tm.tm_sec = sec;

    *out = timegm_fallback(&tm);
    return 1;
}

static char *join_path(const char *a, const char *b) {
    size_t alen = strlen(a);
    size_t blen = strlen(b);
    int need_slash = (alen > 0 && a[alen - 1] != '/');
    size_t out_len = alen + blen + (need_slash ? 2 : 1);
    char *out = (char *)malloc(out_len);
    if (!out) die("malloc");
    if (need_slash) {
        snprintf(out, out_len, "%s/%s", a, b);
    } else {
        snprintf(out, out_len, "%s%s", a, b);
    }
    return out;
}

static void scan_subdir(const char *root, const char *subdir, int is_event, ClipList *list) {
    char *dir_path = join_path(root, subdir);
    DIR *dir = opendir(dir_path);
    if (!dir) {
        fprintf(stderr, "warning: cannot open %s: %s\n", dir_path, strerror(errno));
        free(dir_path);
        return;
    }

    struct dirent *ent;
    while ((ent = readdir(dir)) != NULL) {
        if (ent->d_name[0] == '.') continue;
        if (!ends_with_mp4(ent->d_name)) continue;

        char stamp[16];
        time_t t;
        if (!parse_stamp(ent->d_name, stamp, &t)) continue;

        char *full = join_path(dir_path, ent->d_name);
        Clip c = {0};
        c.path = full;
        c.name = xstrdup(ent->d_name);
        c.source_folder = is_event ? "Event" : "Normal";
        c.is_event = is_event;
        c.start = t;
        memcpy(c.stamp, stamp, 16);
        cliplist_push(list, c);
    }

    closedir(dir);
    free(dir_path);
}

static int clip_cmp(const void *a, const void *b) {
    const Clip *ca = (const Clip *)a;
    const Clip *cb = (const Clip *)b;
    if (ca->start < cb->start) return -1;
    if (ca->start > cb->start) return 1;
    return strcmp(ca->name, cb->name);
}

static void stamp_to_iso(const char *stamp, char out[21]) {
    snprintf(out, 21, "%.4s-%.2s-%.2sT%.2s:%.2s:%.2sZ",
             stamp, stamp + 4, stamp + 6, stamp + 9, stamp + 11, stamp + 13);
}

static int run_exiftool_journey(const Clip *clips, size_t count,
                                const char *fmt_path, const char *out_gpx) {
    size_t base = 8;
    char **args = (char **)calloc(base + count + 1, sizeof(char *));
    if (!args) die("calloc");

    args[0] = "exiftool";
    args[1] = "-d";
    args[2] = "%Y-%m-%dT%H:%M:%SZ";
    args[3] = "-ee";
    args[4] = "-q";
    args[5] = "-q";
    args[6] = "-p";
    args[7] = (char *)fmt_path;
    for (size_t i = 0; i < count; i++) {
        args[base + i] = clips[i].path;
    }
    args[base + count] = NULL;

    pid_t pid = fork();
    if (pid == 0) {
        int fd = open(out_gpx, O_CREAT | O_TRUNC | O_WRONLY, 0644);
        if (fd < 0) _exit(127);
        dup2(fd, STDOUT_FILENO);
        close(fd);
        execvp(args[0], args);
        _exit(127);
    } else if (pid < 0) {
        free(args);
        return -1;
    }

    int status = 0;
    waitpid(pid, &status, 0);
    free(args);

    if (!WIFEXITED(status) || WEXITSTATUS(status) != 0) {
        return -1;
    }
    return 0;
}

static void json_write_string(FILE *f, const char *s) {
    fputc('"', f);
    for (const unsigned char *p = (const unsigned char *)s; *p; p++) {
        switch (*p) {
            case '"':  fputs("\\\"", f); break;
            case '\\': fputs("\\\\", f); break;
            case '\n': fputs("\\n", f); break;
            case '\r': fputs("\\r", f); break;
            case '\t': fputs("\\t", f); break;
            default:
                if (*p < 0x20) {
                    fprintf(f, "\\u%04x", *p);
                } else {
                    fputc(*p, f);
                }
        }
    }
    fputc('"', f);
}

static char *read_file_all(const char *path, size_t *len_out) {
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    if (fseek(f, 0, SEEK_END) != 0) { fclose(f); return NULL; }
    long n = ftell(f);
    if (n < 0) { fclose(f); return NULL; }
    if (fseek(f, 0, SEEK_SET) != 0) { fclose(f); return NULL; }

    char *buf = (char *)malloc((size_t)n + 1);
    if (!buf) { fclose(f); return NULL; }
    size_t read_n = fread(buf, 1, (size_t)n, f);
    fclose(f);
    buf[read_n] = '\0';
    if (len_out) *len_out = read_n;
    return buf;
}

static int find_journeys_bounds(const char *s, size_t len, size_t *start, size_t *end) {
    const char *key = "\"journeys\"";
    const char *p = strstr(s, key);
    if (!p) return 0;

    const char *bracket = strchr(p, '[');
    if (!bracket) return 0;

    size_t i = (size_t)(bracket - s);
    int depth = 0;
    int in_str = 0;

    for (; i < len; i++) {
        char c = s[i];
        if (in_str) {
            if (c == '\\' && i + 1 < len) { i++; continue; }
            if (c == '"') in_str = 0;
            continue;
        }
        if (c == '"') { in_str = 1; continue; }
        if (c == '[') {
            if (depth == 0) *start = i;
            depth++;
        } else if (c == ']') {
            depth--;
            if (depth == 0) {
                *end = i;
                return 1;
            }
        }
    }
    return 0;
}

static int has_non_ws(const char *s, size_t len) {
    for (size_t i = 0; i < len; i++) {
        if (!isspace((unsigned char)s[i])) return 1;
    }
    return 0;
}

static size_t rtrim_ws_len(const char *s, size_t len) {
    while (len > 0 && isspace((unsigned char)s[len - 1])) len--;
    return len;
}

static int max_journey_index(const char *s) {
    int max = 0;
    const char *p = s;
    while ((p = strstr(p, "\"journey_index\"")) != NULL) {
        const char *colon = strchr(p, ':');
        if (!colon) break;
        colon++;
        while (*colon && isspace((unsigned char)*colon)) colon++;
        int val = atoi(colon);
        if (val > max) max = val;
        p = colon;
    }
    return max;
}

static ExistingJourneys load_existing(const char *path) {
    ExistingJourneys ex = {0};
    size_t len = 0;
    char *buf = read_file_all(path, &len);
    if (!buf) return ex;

    size_t start = 0, end = 0;
    if (!find_journeys_bounds(buf, len, &start, &end)) {
        free(buf);
        return ex;
    }

    if (end > start + 1) {
        size_t body_len = end - start - 1;
        ex.body = (char *)malloc(body_len + 1);
        if (!ex.body) die("malloc");
        memcpy(ex.body, buf + start + 1, body_len);
        ex.body[body_len] = '\0';
        ex.body_len = rtrim_ws_len(ex.body, body_len);
        ex.has_existing = has_non_ws(ex.body, ex.body_len);
    }

    ex.max_index = max_journey_index(buf);
    free(buf);
    return ex;
}

static void usage(const char *prog) {
    fprintf(stderr,
        "Usage: %s --root <path> [--fmt <gpx.fmt>] [--gap <seconds>] "
        "[--out-json <file>] [--out-dir <dir>] [--append]\n", prog);
}

int main(int argc, char **argv) {
    const char *root = NULL;
    const char *fmt = "gpx.fmt";
    const char *out_json = "journeys.json";
    const char *out_dir = ".";
    int gap_seconds = 65;
    int append = 0;

    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--root") == 0 && i + 1 < argc) {
            root = argv[++i];
        } else if (strcmp(argv[i], "--fmt") == 0 && i + 1 < argc) {
            fmt = argv[++i];
        } else if (strcmp(argv[i], "--gap") == 0 && i + 1 < argc) {
            gap_seconds = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--out-json") == 0 && i + 1 < argc) {
            out_json = argv[++i];
        } else if (strcmp(argv[i], "--out-dir") == 0 && i + 1 < argc) {
            out_dir = argv[++i];
        } else if (strcmp(argv[i], "--append") == 0) {
            append = 1;
        } else {
            usage(argv[0]);
            return 2;
        }
    }

    if (!root) {
        usage(argv[0]);
        return 2;
    }

    ClipList clips = {0};
    scan_subdir(root, "Normal", 0, &clips);
    scan_subdir(root, "Event", 1, &clips);

    if (clips.len == 0) {
        fprintf(stderr, "No MP4 clips found under Normal or Event.\n");
        return 1;
    }

    qsort(clips.items, clips.len, sizeof(Clip), clip_cmp);

    ExistingJourneys existing = {0};
    if (append) existing = load_existing(out_json);
    int next_index = append ? (existing.max_index + 1) : 1;

    FILE *json = fopen(out_json, "w");
    if (!json) die("fopen");

    char updated_at[21];
    time_t now = time(NULL);
    struct tm tm_now;
    gmtime_r(&now, &tm_now);
    strftime(updated_at, sizeof(updated_at), "%Y-%m-%dT%H:%M:%SZ", &tm_now);

    fprintf(json, "{\n  \"storage_mount\": ");
    json_write_string(json, root);
    fprintf(json, ",\n  \"updated_at\": ");
    json_write_string(json, updated_at);
    fprintf(json, ",\n  \"journeys\": [\n");

    int wrote_any = 0;
    if (append && existing.has_existing) {
        fwrite(existing.body, 1, existing.body_len, json);
        wrote_any = 1;
    }

    size_t i = 0;
    while (i < clips.len) {
        size_t start = i;
        size_t end = i;
        while (end + 1 < clips.len) {
            double delta = difftime(clips.items[end + 1].start, clips.items[end].start);
            if (delta > gap_seconds) break;
            end++;
        }

        char start_iso[21];
        char end_iso[21];
        stamp_to_iso(clips.items[start].stamp, start_iso);
        stamp_to_iso(clips.items[end].stamp, end_iso);

        char gpx_name[128];
        snprintf(gpx_name, sizeof(gpx_name), "journey_%s_to_%s.gpx",
                 clips.items[start].stamp, clips.items[end].stamp);
        char *gpx_path = join_path(out_dir, gpx_name);

        if (run_exiftool_journey(&clips.items[start], end - start + 1, fmt, gpx_path) != 0) {
            fprintf(stderr, "warning: exiftool failed for %s\n", gpx_name);
        }

        if (wrote_any) fprintf(json, ",\n");
        wrote_any = 1;

        int has_events = 0;
        for (size_t j = start; j <= end; j++) {
            if (clips.items[j].is_event) { has_events = 1; break; }
        }

        fprintf(json, "    {\n");
        fprintf(json, "      \"journey_index\": %d,\n", next_index++);
        fprintf(json, "      \"gpx_output_file\": ");
        json_write_string(json, gpx_name);
        fprintf(json, ",\n");
        fprintf(json, "      \"start_time\": ");
        json_write_string(json, start_iso);
        fprintf(json, ",\n");
        fprintf(json, "      \"end_time\": ");
        json_write_string(json, end_iso);
        fprintf(json, ",\n");
        fprintf(json, "      \"has_events\": %s,\n", has_events ? "true" : "false");
        fprintf(json, "      \"video_stitch_list\": [\n");

        size_t order = 1;
        for (size_t j = start; j <= end; j++) {
            fprintf(json, "        {\n");
            fprintf(json, "          \"playback_order\": %zu,\n", order++);
            fprintf(json, "          \"filename\": ");
            json_write_string(json, clips.items[j].name);
            fprintf(json, ",\n");
            fprintf(json, "          \"absolute_path\": ");
            json_write_string(json, clips.items[j].path);
            fprintf(json, ",\n");
            fprintf(json, "          \"source_folder\": ");
            json_write_string(json, clips.items[j].source_folder);
            fprintf(json, ",\n");
            fprintf(json, "          \"is_event\": %s\n", clips.items[j].is_event ? "true" : "false");
            fprintf(json, "        }%s\n", (j < end) ? "," : "");
        }

        fprintf(json, "      ]\n");
        fprintf(json, "    }");

        free(gpx_path);
        i = end + 1;
    }

    fprintf(json, "\n  ]\n}\n");
    fclose(json);

    free(existing.body);
    for (size_t k = 0; k < clips.len; k++) {
        free(clips.items[k].path);
        free(clips.items[k].name);
    }
    free(clips.items);

    return 0;
}