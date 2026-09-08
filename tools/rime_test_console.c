// 真实 librime 会话测试：模拟按键，观察空明码反查行为
// 编译: gcc -o /tmp/rime_test tools/rime_test_console.c -lrime
#include <rime_api.h>
#include <stdio.h>
#include <stdlib.h>

static void on_notify(void* ctx, RimeSessionId session,
                      const char* type, const char* value) {
  printf("[notify] %s: %s\n", type, value ? value : "(null)");
}

static void print_state(RimeApi* api, RimeSessionId session, const char* tag) {
  RimeContext context;
  RIME_STRUCT_INIT(RimeContext, context);
  if (!api->get_context(session, &context)) {
    printf("%-14s | get_context 失败\n", tag);
    return;
  }
  const char* preedit = context.composition.preedit ? context.composition.preedit : "";
  printf("%-14s | preedit='%s' 候选数=%d", tag, preedit, context.menu.num_candidates);
  int show = context.menu.num_candidates > 3 ? 3 : context.menu.num_candidates;
  for (int i = 0; i < show; i++) {
    RimeCandidate* c = &context.menu.candidates[i];
    printf(" | [%d]%s(%s)", i + (context.menu.page_no ? 0 : 0),
           c->text ? c->text : "?", c->comment ? c->comment : "-");
    if (i == 0 && c->comment) {  // [DEBUG-revcm] 首候选注释十六进制
      printf(" HEX:");
      for (const unsigned char* p = (const unsigned char*)c->comment; *p && p < (const unsigned char*)c->comment + 40; p++)
        printf("%02x", *p);
    }
  }
  printf("\n");
  api->free_context(&context);
}

int main(int argc, char** argv) {
  setvbuf(stdout, NULL, _IONBF, 0);  // [DEBUG-revcm] 段错误时保留已打印内容
  const char* schema_id = argc > 1 ? argv[1] : "kongmingma";
  RimeTraits traits;
  RIME_STRUCT_INIT(RimeTraits, traits);
  traits.shared_data_dir = "/usr/share/rime-data";
  traits.user_data_dir = "/home/jackwy/.local/share/fcitx5/rime";
  traits.log_dir = "/home/jackwy/.local/share/fcitx5/rime/.test-logs";
  traits.distribution_name = "Rime";
  traits.distribution_code_name = "rime-test-console";
  traits.distribution_version = "1.0";
  traits.app_name = "rime.rime-test-console";

  RimeApi* api = rime_get_api();
  if (!api) { printf("无法获取 RimeApi\n"); return 1; }
  api->setup(&traits);
  api->set_notification_handler(on_notify, NULL);
  printf("stage: setup done\n"); fflush(stdout);
  api->initialize(NULL);  // 沿用 setup 时的 traits，避免重复应用
  printf("stage: initialize done\n"); fflush(stdout);
  if (api->start_maintenance(/*full_check=*/True))  // 全量部署：编译 luna_pinyin 依赖
    api->join_maintenance_thread();
  printf("stage: maintenance done\n"); fflush(stdout);

  RimeSessionId session = api->create_session();
  if (!session) {
    printf("会话创建失败\n");
    api->finalize();
    return 1;
  }
  printf("stage: session created\n"); fflush(stdout);
  fprintf(stderr, "[DEBUG-revcm] before select_schema\n");
  if (!api->select_schema(session, schema_id)) {
    printf("切换 %s 失败\n", schema_id);
  }
  fprintf(stderr, "[DEBUG-revcm] after select_schema\n");
  printf("=== 基线：simulate fa（并击正常出字，证明无回归）===\n");
  if (api->simulate_key_sequence(session, "fa")) {
    print_state(api, session, "fa");
  }
  api->clear_composition(session);
  fprintf(stderr, "[DEBUG-revcm] after baseline fa\n");

  api->clear_composition(session);
  printf("=== 反查：` fa ===\n");
  if (api->simulate_key_sequence(session, "`fa")) {
    print_state(api, session, "`fa");
  } else {
    printf("simulate_key_sequence 失败\n");
  }
  fprintf(stderr, "[DEBUG-revcm] after fanqiu fa\n");

  api->clear_composition(session);
  printf("=== 反查：` zhongguo ===\n");
  if (api->simulate_key_sequence(session, "`zhongguo")) {
    print_state(api, session, "`zhongguo");
  } else {
    printf("simulate_key_sequence 失败\n");
  }

  { /* [DEBUG-revcm] 多字词对照：luna 与主码表都有的词 */
    const char* probes[] = {"`jiuxing", "`diwei", "`zhongyao", "`difang", "`women"};
    for (int i = 0; i < 5; i++) {
      fprintf(stderr, "[DEBUG-revcm] probe %d: %s\n", i, probes[i]);
      api->clear_composition(session);
      if (api->simulate_key_sequence(session, probes[i]))
        print_state(api, session, probes[i]);
      fprintf(stderr, "[DEBUG-revcm] probe %d done\n", i);
    }
  }

  api->clear_composition(session);
  printf("=== 反查选字：` fa + 空格 ===\n");
  if (api->simulate_key_sequence(session, "`fa")) {
    print_state(api, session, "`fa");
  }
  api->process_key(session, 0x20, 0);  // 空格选首候选
  api->process_key(session, 0x20, 1);  // 释放
  RimeCommit commit;
  RIME_STRUCT_INIT(RimeCommit, commit);
  if (api->get_commit(session, &commit) && commit.text) {
    printf("上屏文本: %s\n", commit.text);
    api->free_commit(&commit);
  }
  api->free_commit(&commit);
  api->destroy_session(session);
  api->finalize();
  return 0;
}
