/* km_probe_chord.c —— 用 librime 实测「一次并击输出什么码」，用于验证简码/击数口径。
 *
 * 为什么需要它：kongmingmas 的码不是「一个字符 = 一次按键」，而是
 * chord_composer 先把这一击的按键序列化成一个串，再过 algebra 变换。
 * 光读 schema 猜规则很容易错（本仓历史上就错过两次：`RI` vs `RG`、`X_=` 算不算 1 击）。
 * 这个探针直接喂按键事件给 librime，把引擎真实收到的输入码打印出来，是唯一可靠的判据。
 *
 * 编译：
 *     gcc -O1 -o /tmp/probe km_probe_chord.c -lrime
 *
 * 准备一个「只保留 algebra 的最小方案」（词典极小，部署几秒）：
 *     把 kongmingmas.schema.yaml 里 chord_composer 段整段抄进 probe.schema.yaml，
 *     speller/alphabet 抄原方案的，processor 链要有 ascii_composer + chord_composer + speller + express_editor。
 *     注意：测「码」时要把 speller.auto_select 关掉，否则一击命中会直接上屏，get_input() 读到空串。
 *
 * 用法：
 *     ./probe <shared_dir> <user_dir>              # 枚举 26 字母的单键 / 单键+空格
 *     ./probe <shared_dir> <user_dir> dr qt dv k   # 指定组合：token 内字符同时按下，'^' 代表空格
 *
 * 实测结论（2026-11-15，kongmingmas）：
 *     d        → d=      （左手单键）
 *     k        → =d      （右手单键，左右手互为镜像）
 *     d + 空格 → d_=
 *     k + 空格 → =_d
 *     dv       → D=      （同一只手内两键并击，仍然只算一击）
 *     e+t+h+k（左右手同时）→ RG   ← 一次并击就能出 RG，词库键正是这个
 *     a+s+d+f+j（左右手同时）→ 0f
 *     a+s+d+f+y+o          → 0Y
 *
 * 注意：`RG` / `0Y` / `*c` 都是 **1 击**——左手出一个码元、右手出一个码元，同时按下。
 * 早前把它们当「两次并击」是错的（用单手组合去测，才会打出 `R=G=` 这种不存在的码）。
 * 逐条核对 algebra 的通用模型见 tools/km_chord_model.py，本探针只做事后抽查。
 */
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <stdlib.h>
#include <rime_api.h>

#define RELEASE_MASK (1 << 30)

static RimeApi* api;
static RimeSessionId S;

static void run(const char* label, const int* keys, int n) {
  for (int i = 0; i < n; i++) api->process_key(S, keys[i], 0);
  for (int i = 0; i < n; i++) api->process_key(S, keys[i], RELEASE_MASK);

  const char* input = api->get_input(S);
  RIME_STRUCT(RimeCommit, commit);
  char* commit_text = NULL;
  if (api->get_commit(S, &commit)) commit_text = strdup(commit.text ? commit.text : "");

  RIME_STRUCT(RimeContext, ctx);
  char buf[512] = {0};
  if (api->get_context(S, &ctx)) {
    int n2 = ctx.menu.num_candidates;
    if (n2 > 5) n2 = 5;
    for (int i = 0; i < n2; i++) {
      strncat(buf, ctx.menu.candidates[i].text, 64);
      if (i + 1 < n2) strncat(buf, "|", 2);
    }
    api->free_context(&ctx);
  }
  printf("%-10s code=%-8s commit=%-8s cand=%s\n", label,
         input ? input : "(null)", commit_text ? commit_text : "-", buf);
  fflush(stdout);
  if (commit_text) free(commit_text);
  api->clear_composition(S);
}

int main(int argc, char** argv) {
  api = rime_get_api();
  RIME_STRUCT(RimeTraits, traits);
  traits.shared_data_dir = argv[1];
  traits.user_data_dir = argv[2];
  traits.distribution_name = "Rime";
  traits.distribution_code_name = "rime";
  traits.distribution_version = "1.17.0";
  traits.app_name = "rime.probe";
  traits.min_log_level = 2;
  traits.log_dir = "";

  api->initialize(&traits);
  api->start_maintenance(True);
  api->join_maintenance_thread();
  S = api->create_session();
  if (!S) { printf("no session\n"); return 1; }
  api->select_schema(S, "probe");
  printf("schema ok\n");
  fflush(stdout);

  if (argc > 3) {
    for (int a = 3; a < argc; a++) {
      int keys[8];
      int n = 0;
      for (const char* p = argv[a]; *p && n < 8; p++)
        keys[n++] = (*p == '^') ? 0x20 : (int)*p;
      run(argv[a], keys, n);
    }
    api->finalize();
    return 0;
  }

  static char label[32];
  for (char c = 'a'; c <= 'z'; c++) {
    int k1[1] = {c};
    snprintf(label, sizeof label, "%c", c);
    run(label, k1, 1);
    int k2[2] = {c, 0x20};
    snprintf(label, sizeof label, "%c+sp", c);
    run(label, k2, 2);
  }
  api->finalize();
  return 0;
}
