#define ImDrawIdx unsigned int

#include <iostream>
#include <string>
#include <vector>
#include <algorithm>
#include <cmath>
#include <chrono>
#include <optional>
#include <sstream>
#include <cstdlib>

// Windows API for fullscreen + file dialog
#include <windows.h>

// OpenCV
#include <opencv2/opencv.hpp>

// SFML
#include <SFML/Graphics.hpp>
#include <SFML/Audio.hpp>

// ImGui
#include "imgui.h"
#include "imgui-SFML.h"

// ─── Palettes ────────────────────────────────────────────────────────────────
const std::string PALETTE_SIMPLE_DARK    = " .,;:+*?%S#@";
const std::string PALETTE_SIMPLE_LIGHT   = "@#S%?*+;:,. ";
const std::string PALETTE_DETAILED_DARK  = " `^\".,;:Ili!<>~+_-?][}{1)(|/\\ftjrxnuvczXYUJCLQ0OZmwqpdkbhao*$B%8&WM#@";
const std::string PALETTE_DETAILED_LIGHT = "@#MW&8%B$*oahkbdpqwmZO0QLCJUYXzcvunxrjft/\\|()1{}[]?-_+~<>i!lI;:,\"^`. ";

// ─── Resolution Presets ───────────────────────────────────────────────────────
struct ResPreset { std::string name; int max_chars; };
const std::vector<ResPreset> RESOLUTIONS = {
    {"Hyper 8K Simulation",  80000},
    {"Cinematic Max Master", 60000},
    {"Cinematic Extreme",    45000},
    {"Ultra HD++",           30000},
    {"Ultra HD+",            20000},
    {"Ultra HD",             15000},
    {"Super High",           10000},
    {"High Detail",           7000},
    {"Standard Balanced",     4500},
    {"Medium Profile",        2500},
    {"Low Detail",            1500},
    {"Retro Terminal",         800},
    {"GameBoy Retro",          400}
};

// ─── Color Palette ────────────────────────────────────────────────────────────
std::vector<sf::Color> init_color_palette() {
    std::vector<sf::Color> p;
    for (int r = 0; r <= 255; r += 51)
        for (int g = 0; g <= 255; g += 51)
            for (int b = 0; b <= 255; b += 51)
                p.push_back(sf::Color(r, g, b));
    return p;
}
const std::vector<sf::Color> COLOR_PALETTE_RGB = init_color_palette();

// ─── Helpers ──────────────────────────────────────────────────────────────────
std::string fmt_time(double seconds) {
    int s = std::max(0, (int)seconds);
    int m = s / 60; s %= 60;
    int h = m / 60; m %= 60;
    char buf[32];
    if (h > 0) sprintf(buf, "%d:%02d:%02d", h, m, s);
    else        sprintf(buf, "%d:%02d", m, s);
    return buf;
}

// ─── Native Windows File Dialog ───────────────────────────────────────────────
std::string open_file_dialog() {
    char buf[512] = "";
    OPENFILENAMEA ofn     = {};
    ofn.lStructSize       = sizeof(ofn);
    ofn.lpstrFilter       =
        "Video/Image Files\0*.mp4;*.avi;*.mkv;*.mov;*.png;*.jpg;*.jpeg;*.bmp\0"
        "All Files\0*.*\0";
    ofn.lpstrFile         = buf;
    ofn.nMaxFile          = sizeof(buf);
    ofn.lpstrTitle        = "Select a Video or Image File";
    ofn.Flags             = OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST;
    if (GetOpenFileNameA(&ofn)) return std::string(buf);
    return "";
}

// ─── Frame to ASCII ───────────────────────────────────────────────────────────
void frame_to_ascii(const cv::Mat& frame, int cols, int rows,
                    const std::string& palette, bool use_color, float zoom,
                    std::vector<std::string>& out_lines,
                    std::vector<std::vector<int>>& out_colors,
                    float font_aspect = 0.5f) {
    if (frame.empty()) return;

    cv::Mat src = frame;
    if (zoom > 1.0f) {
        int cw = std::clamp((int)(src.cols / zoom), 1, src.cols);
        int ch = std::clamp((int)(src.rows / zoom), 1, src.rows);
        src = src(cv::Rect((src.cols - cw) / 2, (src.rows - ch) / 2, cw, ch));
    }

    float vid_asp  = (float)src.cols / src.rows;
    float tgt_asp  = vid_asp / font_aspect;
    float grid_asp = (float)cols / rows;

    int tw, th;
    if (tgt_asp > grid_asp) { tw = cols; th = std::max(1, (int)(cols / tgt_asp)); }
    else                    { th = rows; tw = std::max(1, (int)(rows * tgt_asp)); }
    tw = std::min(tw, cols);
    th = std::min(th, rows);

    cv::Mat resized;
    cv::cvtColor(src, resized, cv::COLOR_BGR2RGB);
    cv::resize(resized, resized, cv::Size(tw, th), 0, 0, cv::INTER_LINEAR);

    out_lines.assign(rows,  std::string(cols, ' '));
    out_colors.assign(rows, std::vector<int>(cols, 0));

    int xo = (cols - tw) / 2;
    int yo = (rows - th) / 2;
    int pl = (int)palette.size() - 1;

    for (int y = 0; y < th && (yo+y) < rows; ++y) {
        for (int x = 0; x < tw && (xo+x) < cols; ++x) {
            cv::Vec3b px = resized.at<cv::Vec3b>(y, x);
            float gray   = 0.299f*px[0] + 0.587f*px[1] + 0.114f*px[2];
            int idx      = std::clamp((int)((gray/255.f)*pl), 0, pl);
            out_lines [yo+y][xo+x] = palette[idx];
            if (use_color) {
                int ri = px[0]/51, gi = px[1]/51, bi = px[2]/51;
                out_colors[yo+y][xo+x] = std::clamp(ri*36 + gi*6 + bi, 0, 215);
            }
        }
    }
}

// ─── Tooltip helper (3 second delay) ─────────────────────────────────────────
void tip(const char* msg) {
    if (ImGui::IsItemHovered(ImGuiHoveredFlags_StationaryTime) &&
        ImGui::GetCurrentContext()->HoveredIdTimer > 3.0f)
        ImGui::SetTooltip("%s", msg);
}

// ─── Main ─────────────────────────────────────────────────────────────────────
int main() {

    bool  media_loaded = false, is_image     = false;
    bool  audio_loaded = false, paused       = false;
    bool  use_color    = false, use_detailed = false;
    bool  invert_pal   = false, fullscreen   = false;

    char        path_buffer[512] = "";
    std::string media_path       = "";
    std::string temp_audio       = "cstage_temp_audio.wav";

    cv::VideoCapture cap;
    cv::Mat          static_image, frame;
    double fps          = 24.0;
    int    total_frames = 1, current_frame_idx = 0;
    float  video_aspect = 16.f / 9.f;

    sf::Music music;
    float volume      = 100.f;
    float font_aspect = 0.5f;

    int   selected_preset = 8;
    int   cols = 80, rows = 24;
    float zoom_factor = 1.f;
    float player_w = 1004.f, player_h = 533.f;

    std::vector<std::string>      ascii_lines;
    std::vector<std::vector<int>> ascii_colors;

    // ── Window ────────────────────────────────────────────────────────────
    sf::RenderWindow window(sf::VideoMode({1024, 768}), "CStage", sf::Style::Default);
    window.setFramerateLimit(60);
    if (!ImGui::SFML::Init(window)) return -1;

    auto apply_theme = [&]() {
        ImGui::StyleColorsDark();
        ImGuiStyle& s = ImGui::GetStyle();
        s.Colors[ImGuiCol_Text]     = ImVec4(0.f, 1.f, 0.53f, 1.f);
        s.Colors[ImGuiCol_WindowBg] = ImVec4(0.05f, 0.05f, 0.05f, 1.f);
        s.Colors[ImGuiCol_FrameBg]  = ImVec4(0.08f, 0.08f, 0.08f, 1.f);
        s.HoverStationaryDelay      = 3.0f; // 3 sec tooltip delay globally
    };
    apply_theme();

    sf::Clock deltaClock;
    auto last_frame_time = std::chrono::steady_clock::now();

    // ── Grid calculator ────────────────────────────────────────────────────
    auto update_grid = [&]() {
        const float MIN_PX_W = 9.f, MIN_PX_H = 14.f;
        float adj  = video_aspect / font_aspect;
        int budget = std::min(RESOLUTIONS[selected_preset].max_chars,
                              (int)((player_w / MIN_PX_W) * (player_h / MIN_PX_H)));
        rows = std::max(5, (int)std::sqrt((float)budget / adj));
        cols = std::max(5, (int)(rows * adj));
    };

    // ── Fullscreen via Windows API — no window recreation, no crash ────────
    auto toggle_fullscreen = [&]() {
        fullscreen = !fullscreen;
        HWND hwnd  = window.getNativeHandle();
        if (fullscreen) {
            int sw = GetSystemMetrics(SM_CXSCREEN);
            int sh = GetSystemMetrics(SM_CYSCREEN);
            SetWindowLongA(hwnd, GWL_STYLE, WS_POPUP | WS_VISIBLE);
            SetWindowPos(hwnd, HWND_TOP, 0, 0, sw, sh, SWP_FRAMECHANGED);
        } else {
            SetWindowLongA(hwnd, GWL_STYLE, WS_OVERLAPPEDWINDOW | WS_VISIBLE);
            SetWindowPos(hwnd, NULL, 100, 100, 1024, 768, SWP_FRAMECHANGED);
        }
    };

    // ── Unload ────────────────────────────────────────────────────────────
    auto unload_media = [&]() {
        if (cap.isOpened()) cap.release();
        static_image.release(); frame.release();
        music.stop();
        std::remove(temp_audio.c_str());
        audio_loaded = false; media_loaded = false;
        current_frame_idx = 0; total_frames = 1;
        video_aspect = 16.f / 9.f;
    };

    // ── Load ──────────────────────────────────────────────────────────────
    auto load_media = [&](const std::string& path) {
        unload_media();
        media_path = path;
        std::string ext = path.substr(path.find_last_of('.') + 1);
        std::transform(ext.begin(), ext.end(), ext.begin(), ::tolower);

        if (ext == "png" || ext == "jpg" || ext == "jpeg" || ext == "bmp") {
            is_image     = true;
            static_image = cv::imread(path);
            if (!static_image.empty()) {
                video_aspect = (float)static_image.cols / static_image.rows;
                media_loaded = true;
            }
        } else {
            is_image = false;
            if (cap.open(path)) {
                fps          = cap.get(cv::CAP_PROP_FPS);
                if (fps <= 0) fps = 24.0;
                total_frames = std::max(1, (int)cap.get(cv::CAP_PROP_FRAME_COUNT));
                float vw     = cap.get(cv::CAP_PROP_FRAME_WIDTH);
                float vh     = cap.get(cv::CAP_PROP_FRAME_HEIGHT);
                video_aspect = vh > 0 ? vw / vh : 16.f / 9.f;
                media_loaded = true;

                // Extract audio via ffmpeg → WAV (SFML can't read AAC from mp4)
                std::string cmd = "ffmpeg -y -i \"" + path +
                    "\" -vn -ar 44100 -ac 2 -f wav \"" +
                    temp_audio + "\" >nul 2>&1";
                system(cmd.c_str());

                if (music.openFromFile(temp_audio)) {
                    audio_loaded = true;
                    music.setVolume(volume);
                    music.play();
                }
            }
        }
    };

    // ══════════════════════════════════════════════════════════════════════
    while (window.isOpen()) {

        while (const std::optional event = window.pollEvent()) {
            ImGui::SFML::ProcessEvent(window, *event);
            if (event->is<sf::Event::Closed>()) window.close();
            if (const auto* kp = event->getIf<sf::Event::KeyPressed>()) {
                if (kp->code == sf::Keyboard::Key::F11)
                    toggle_fullscreen();
                if (kp->code == sf::Keyboard::Key::Space &&
                    media_loaded && !is_image &&
                    !ImGui::GetIO().WantCaptureKeyboard) {
                    paused = !paused;
                    if (audio_loaded) { if (paused) music.pause(); else music.play(); }
                }
            }
        }

        ImGui::SFML::Update(window, deltaClock.restart());

        // Measure real font aspect
        {
            float cw = ImGui::GetFont()->CalcTextSizeA(
                           ImGui::GetFontSize(), FLT_MAX, 0.f, "X").x;
            float ch = ImGui::GetTextLineHeight();
            if (cw > 0.f && ch > 0.f) font_aspect = cw / ch;
        }

        // Layout — before grid calc
        float screen_w = ImGui::GetIO().DisplaySize.x;
        float screen_h = ImGui::GetIO().DisplaySize.y;
        const float TOP = 25.f, BOT_H = 195.f, GAP = 10.f;
        player_w = screen_w - GAP * 2.f;
        player_h = screen_h - TOP - BOT_H - GAP * 2.f;
        update_grid();

        // Frame timing
        if (media_loaded && !is_image && !paused) {
            auto now = std::chrono::steady_clock::now();
            std::chrono::duration<double> elapsed = now - last_frame_time;
            if (elapsed.count() >= 1.0 / fps) {
                cap >> frame;
                if (frame.empty()) {
                    cap.set(cv::CAP_PROP_POS_FRAMES, 0);
                    if (audio_loaded) { music.stop(); music.play(); }
                    cap >> frame;
                }
                current_frame_idx = (int)cap.get(cv::CAP_PROP_POS_FRAMES);
                last_frame_time   = now;
            }
        } else if (media_loaded && is_image) {
            frame = static_image;
        }

        // Palette
        const std::string& pal = invert_pal
            ? (use_detailed ? PALETTE_DETAILED_LIGHT : PALETTE_SIMPLE_LIGHT)
            : (use_detailed ? PALETTE_DETAILED_DARK  : PALETTE_SIMPLE_DARK);

        if (media_loaded && !frame.empty())
            frame_to_ascii(frame, cols, rows, pal, use_color, zoom_factor,
                           ascii_lines, ascii_colors, font_aspect);

        // ── Menu Bar ──────────────────────────────────────────────────────
        if (ImGui::BeginMainMenuBar()) {
            if (ImGui::BeginMenu("File")) {
                if (ImGui::MenuItem("Browse File...")) {
                    std::string picked = open_file_dialog();
                    if (!picked.empty()) {
                        strncpy(path_buffer, picked.c_str(), sizeof(path_buffer)-1);
                        load_media(picked);
                    }
                }
                if (ImGui::MenuItem("Unload Asset")) unload_media();
                ImGui::Separator();
                if (ImGui::MenuItem("Exit Engine"))  window.close();
                ImGui::EndMenu();
            }
            if (ImGui::BeginMenu("View")) {
                if (ImGui::MenuItem(fullscreen
                    ? "Exit Fullscreen (F11)" : "Enter Fullscreen (F11)"))
                    toggle_fullscreen();
                ImGui::EndMenu();
            }
            ImGui::EndMainMenuBar();
        }

        // ── ASCII Projection Screen ───────────────────────────────────────
        ImGui::SetNextWindowPos(ImVec2(GAP, TOP));
        ImGui::SetNextWindowSize(ImVec2(player_w, player_h));
        ImGui::Begin("ASCII Projection Screen", nullptr,
            ImGuiWindowFlags_NoMove | ImGuiWindowFlags_NoScrollbar |
            ImGuiWindowFlags_NoScrollWithMouse | ImGuiWindowFlags_NoCollapse);

        if (media_loaded && !ascii_lines.empty()) {
            ImVec2 avail = ImGui::GetContentRegionAvail();
            float  cw    = ImGui::GetFont()->CalcTextSizeA(
                               ImGui::GetFontSize(), FLT_MAX, 0.f, "X").x;
            float  ch    = ImGui::GetTextLineHeight();
            float  scale = std::min(avail.x / (cols * cw),
                                    avail.y / (rows * ch));
            if (scale < 0.05f) scale = 0.05f;

            float cx = std::max(0.f, (avail.x - cols * cw * scale) / 2.f);
            float cy = std::max(0.f, (avail.y - rows * ch * scale) / 2.f);

            // DrawList — zero gap pixel-perfect rendering
            ImDrawList* draw    = ImGui::GetWindowDrawList();
            ImVec2      win_pos = ImGui::GetWindowPos();
            ImVec2      content = ImGui::GetCursorPos();

            float base_x = win_pos.x + content.x + cx;
            float base_y = win_pos.y + content.y + cy;
            float cw_s   = cw * scale;
            float ch_s   = ch * scale;
            ImFont* font    = ImGui::GetFont();
            float   font_sz = ImGui::GetFontSize() * scale;
            ImU32   green   = IM_COL32(0, 255, 135, 255);

            for (int y = 0; y < rows; ++y) {
                if (y >= (int)ascii_lines.size()) break;
                for (int x = 0; x < cols; ++x) {
                    if (x >= (int)ascii_lines[y].size()) break;
                    char c = ascii_lines[y][x];
                    if (c == ' ') continue;

                    ImU32 color = green;
                    if (use_color && !ascii_colors.empty()) {
                        sf::Color sc = COLOR_PALETTE_RGB[ascii_colors[y][x]];
                        color = IM_COL32(sc.r, sc.g, sc.b, 255);
                    }
                    char buf[2] = {c, '\0'};
                    draw->AddText(font, font_sz,
                        ImVec2(base_x + x * cw_s, base_y + y * ch_s),
                        color, buf);
                }
            }
            ImGui::Dummy(ImVec2(avail.x, avail.y));

        } else {
            ImVec2 avail = ImGui::GetContentRegionAvail();
            const char* msg =
                "ENGINE STANDBY: Load a video asset or photo to begin rendering process.";
            float tw = ImGui::GetFont()->CalcTextSizeA(
                           ImGui::GetFontSize(), FLT_MAX, 0.f, msg).x;
            ImGui::SetCursorPos(ImVec2((avail.x - tw) / 2.f, avail.y / 2.f));
            ImGui::TextUnformatted(msg);
        }
        ImGui::End();

        // ── Control Deck ──────────────────────────────────────────────────
        ImGui::SetNextWindowPos(ImVec2(GAP, screen_h - BOT_H - GAP));
        ImGui::SetNextWindowSize(ImVec2(player_w, BOT_H));
        ImGui::Begin("Control Deck", nullptr,
            ImGuiWindowFlags_NoTitleBar | ImGuiWindowFlags_NoResize |
            ImGuiWindowFlags_NoCollapse);

        // Path row
        ImGui::Text("Asset File Path Target:");
        ImGui::SetNextItemWidth(player_w - 310.f);
        ImGui::InputTextWithHint("##path",
            "Type file path or use Browse...",
            path_buffer, IM_ARRAYSIZE(path_buffer));
        tip("Enter the full or relative path to your video or image file");

        ImGui::SameLine();
        if (ImGui::Button("Browse...")) {
            std::string picked = open_file_dialog();
            if (!picked.empty()) {
                strncpy(path_buffer, picked.c_str(), sizeof(path_buffer)-1);
                load_media(picked);
            }
        }
        tip("Open a file picker to browse for a video or image");

        ImGui::SameLine();
        if (ImGui::Button("Load")) load_media(std::string(path_buffer));
        tip("Load the file at the typed path into the engine");

        ImGui::Separator();
        ImGui::Columns(2, "deck", false);
        ImGui::SetColumnWidth(0, player_w * 0.60f);

        // Left — playback
        if (media_loaded && !is_image) {
            if (ImGui::Button(paused ? " Play " : "Pause")) {
                paused = !paused;
                if (audio_loaded) { if (paused) music.pause(); else music.play(); }
            }
            tip("Play / Pause the video (Space)");

            ImGui::SameLine();
            if (ImGui::Button("Restart")) {
                cap.set(cv::CAP_PROP_POS_FRAMES, 0);
                current_frame_idx = 0;
                if (audio_loaded) {
                    music.stop();
                    music.setPlayingOffset(sf::Time::Zero);
                    music.play();
                }
            }
            tip("Restart video from the beginning");

            ImGui::SameLine();
            ImGui::SetNextItemWidth(200.f);
            int seek = current_frame_idx;
            if (ImGui::SliderInt("##seek", &seek, 0, total_frames - 1, "")) {
                current_frame_idx = seek;
                cap.set(cv::CAP_PROP_POS_FRAMES, seek);
                if (audio_loaded)
                    music.setPlayingOffset(sf::seconds(seek / (float)fps));
            }
            tip("Drag to seek through the video");

            ImGui::SameLine();
            ImGui::Text("%s / %s",
                fmt_time(current_frame_idx / fps).c_str(),
                fmt_time(total_frames      / fps).c_str());
        } else if (media_loaded && is_image) {
            ImGui::Text("Static Image Channel Active");
        } else {
            ImGui::Text("No Active Video Track.");
        }

        ImGui::Spacing();
        ImGui::SetNextItemWidth(160.f);
        ImGui::SliderFloat("Zoom", &zoom_factor, 1.f, 4.f, "%.2fx");
        tip("Zoom into the center of the video");

        ImGui::SameLine();
        ImGui::SetNextItemWidth(160.f);
        if (ImGui::SliderFloat("Volume", &volume, 0.f, 100.f, "%.0f%%"))
            if (audio_loaded) music.setVolume(volume);
        tip("Adjust audio playback volume");

        // Right — toggles + resolution
        ImGui::NextColumn();

        if (ImGui::Button(use_color ? "Color: ON" : "Color: OFF"))
            use_color = !use_color;
        tip("Toggle colored ASCII output (slower at high resolutions)");

        ImGui::SameLine();
        if (ImGui::Button(use_detailed ? "Palette: Detail" : "Palette: Simple"))
            use_detailed = !use_detailed;
        tip("Simple palette: fewer characters. Detail palette: more shading levels");

        ImGui::SameLine();
        if (ImGui::Button(invert_pal ? "Invert: ON" : "Invert: OFF"))
            invert_pal = !invert_pal;
        tip("Invert the character palette for light background videos");

        ImGui::SameLine();
        if (ImGui::Button(fullscreen ? "[WIN]" : "[FULL]"))
            toggle_fullscreen();
        tip("Toggle borderless fullscreen mode (F11)");

        ImGui::Spacing();
        ImGui::SetNextItemWidth(210.f);
        if (ImGui::BeginCombo("Resolution",
                RESOLUTIONS[selected_preset].name.c_str())) {
            for (int i = 0; i < (int)RESOLUTIONS.size(); ++i) {
                bool sel = selected_preset == i;
                if (ImGui::Selectable(RESOLUTIONS[i].name.c_str(), sel))
                    selected_preset = i;
                if (sel) ImGui::SetItemDefaultFocus();
            }
            ImGui::EndCombo();
        }
        tip("Higher resolution = more ASCII detail but smaller characters");

        ImGui::SameLine();
        ImGui::TextDisabled("%dx%d", cols, rows);
        tip("Current ASCII grid dimensions (columns x rows)");

        ImGui::SameLine();
        if (audio_loaded)
            ImGui::TextColored(ImVec4(0.f, 1.f, 0.5f, 1.f), "[AUDIO OK]");
        else if (media_loaded && !is_image)
            ImGui::TextColored(ImVec4(1.f, 0.4f, 0.4f, 1.f), "[NO AUDIO]");
        tip(audio_loaded
            ? "Audio extracted and playing via ffmpeg"
            : "No audio found or ffmpeg extraction failed");

        ImGui::Columns(1);
        ImGui::End();

        // Render
        window.clear(sf::Color(13, 13, 13));
        ImGui::SFML::Render(window);
        window.display();
    }

    ImGui::SFML::Shutdown();
    music.stop();
    std::remove(temp_audio.c_str());
    return 0;
}