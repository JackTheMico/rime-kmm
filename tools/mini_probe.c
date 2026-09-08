// [DEBUG-revcm] 最小 librime 环境探测
#include <rime_api.h>
#include <stdio.h>

int main(void) {
  setvbuf(stdout, NULL, _IONBF, 0);
  printf("A: api 获取前\n");
  RimeApi* api = rime_get_api();
  printf("B: api=%p\n", (void*)api);
  if (!api) return 1;
  RimeTraits traits;
  RIME_STRUCT_INIT(RimeTraits, traits);
  traits.shared_data_dir = "/usr/share/rime-data";
  traits.user_data_dir = "/home/jackwy/.local/share/fcitx5/rime";
  traits.log_dir = "/home/jackwy/.local/share/fcitx5/rime/.test-logs";
  traits.app_name = "rime.mini-probe";
  printf("C: setup 前\n");
  api->setup(&traits);
  printf("D: setup 后\n");
  api->initialize(NULL);
  printf("E: initialize 后\n");
  RimeSessionId s = api->create_session();
  printf("F: session=%lu\n", (unsigned long)s);
  api->finalize();
  printf("G: 完\n");
  return 0;
}
