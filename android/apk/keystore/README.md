# 测试签名（不要当正式密钥）

`debug-test-only.jks` 是**测试专用**密钥，打进仓库只为了让每一份 CI 包用同一把钥匙。这样以后的版本可以 `adb install -r` 和在应用里覆盖安装，不用卸掉再装。

它不是上架密钥。密码写在仓库里，任何人都能用它签名。不要拿它发 Play 商店的包。

| 项 | 值 |
|---|---|
| 文件 | `android/apk/keystore/debug-test-only.jks` |
| 格式 | PKCS12 |
| 别名 | `lorabge-test` |
| 库密码 | `lorabge-test-only` |
| 密钥密码 | `lorabge-test-only` |
| 证书 | `CN=LoRA-bge test only` |

Gradle 在这四个环境变量都有值时改用它们，不再用上面这把测试钥匙：

- `ANDROID_KEYSTORE_B64`：keystore 文件的 base64（一行，不要换行）
- `ANDROID_KEYSTORE_PASS`
- `ANDROID_KEY_ALIAS`
- `ANDROID_KEY_PASS`

GitHub Actions 里对应同名的仓库 Secrets。本仓库的自动化账号不能替你写入 Secrets。要换成私钥时，在自己的电脑上执行（不要把私钥提交进 git）：

```bash
base64 -w0 release.jks | gh secret set ANDROID_KEYSTORE_B64 --repo kingshuoxu/LoRA-bge-long-memory
gh secret set ANDROID_KEYSTORE_PASS --repo kingshuoxu/LoRA-bge-long-memory
gh secret set ANDROID_KEY_ALIAS --repo kingshuoxu/LoRA-bge-long-memory
gh secret set ANDROID_KEY_PASS --repo kingshuoxu/LoRA-bge-long-memory
```

换钥匙会再改一次签名。已经装上测试钥匙包的手机要再卸一次。在决定换成私钥之前，不要设置这四个 Secrets，否则下一版又对不上现在这把测试钥匙。
