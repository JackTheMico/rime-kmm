/* km_deploy：调用 librime 把 Rime 方案编译到 XSIME 的 learning 目录。
 *
 * 用法：km_deploy <shared_data_dir> <user_data_dir>
 *
 * 说明：librime 的部署以「主方案文件是否变过」为触发条件，只改依赖词库
 * 不会重编。这里先把 build/ 里的主方案副本挪走（失败则挪回），
 * 强制走一次完整方案部署，连带重编核心库 / 后缀库等依赖词典。
 */
#include <rime_api.h>
#include <stdio.h>
#include <unistd.h>

#define MAIN_SCHEMA "kongmingmas.schema.yaml"

static int move_aside(const char *build_dir, char *bak, size_t n) {
  snprintf(bak, n, "%s/%s.bak", build_dir, MAIN_SCHEMA);
  char path[4096];
  snprintf(path, sizeof path, "%s/%s", build_dir, MAIN_SCHEMA);
  if (access(path, F_OK) != 0) {
    bak[0] = '\0';
    return 0;
  }
  return rename(path, bak);
}

int main(int argc, char **argv) {
  if (argc < 3) {
    fprintf(stderr, "usage: km_deploy <shared_data_dir> <user_data_dir>\n");
    return 2;
  }
  char build_dir[4096];
  snprintf(build_dir, sizeof build_dir, "%s/build", argv[2]);
  char bak[4200];
  move_aside(build_dir, bak, sizeof bak);

  RIME_STRUCT(RimeTraits, traits);
  traits.shared_data_dir = argv[1];
  traits.user_data_dir = argv[2];
  traits.distribution_name = "Rime";
  traits.distribution_code_name = "rime";
  traits.distribution_version = "1.0";
  traits.app_name = "rime";

  RimeApi *api = rime_get_api();
  api->initialize(&traits);
  api->start_maintenance(False);
  api->join_maintenance_thread();
  api->finalize();

  char path[4096];
  snprintf(path, sizeof path, "%s/%s", build_dir, MAIN_SCHEMA);
  if (bak[0] && access(path, F_OK) != 0) {
    rename(bak, path); /* 编译没产出，恢复原副本 */
    fprintf(stderr, "deploy produced no schema copy\n");
    return 1;
  }
  if (bak[0]) {
    unlink(bak);
  }
  return 0;
}
