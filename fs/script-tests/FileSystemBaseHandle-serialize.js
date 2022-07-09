'use strict';

directory_test(async (t, root_dir) => {
  assert_equals(await root_dir.serialize(), await root_dir.serialize());

  const subdir = await createDirectory(t, 'subdir-name', root_dir);
  assert_equals(await subdir.serialize(), await subdir.serialize());
}, 'serialization for identical directory handles returns identical hashes');

directory_test(async (t, root_dir) => {
  const subdir = await createDirectory(t, 'subdir-name', root_dir);

  assert_not_equals(await root_dir.serialize(), await subdir.serialize());
}, 'serialization for different directories returns different hashes');

directory_test(async (t, root_dir) => {
  const subdir = await createDirectory(t, 'subdir-name', root_dir);
  const subdir2 = await root_dir.getDirectoryHandle('subdir-name');

  assert_equals(await subdir.serialize(), await subdir2.serialize());
}, 'serialization for different handles for the same directory returns identical hashes');

directory_test(async (t, root_dir) => {
  const handle = await createEmptyFile(t, 'mtime.txt', root_dir);

  assert_equals(await handle.serialize(), await handle.serialize());
}, 'serialization for identical file handles returns identical hashes');

directory_test(async (t, root_dir) => {
  const handle1 = await createEmptyFile(t, 'mtime.txt', root_dir);
  const handle2 = await createEmptyFile(t, 'foo.txt', root_dir);

  assert_not_equals(await handle1.serialize(), await handle2.serialize());
}, 'serialization for different files returns different hashes');

directory_test(async (t, root_dir) => {
  const handle1 = await createEmptyFile(t, 'mtime.txt', root_dir);
  const handle2 = await root_dir.getFileHandle('mtime.txt');

  assert_equals(await handle1.serialize(), await handle2.serialize());
}, 'serialization for different handles for the same file returns identical hashes');

directory_test(async (t, root_dir) => {
  const handle1 = await createEmptyFile(t, 'mtime.txt', root_dir);
  const subdir = await createDirectory(t, 'subdir-name', root_dir);
  const handle2 = await createEmptyFile(t, 'mtime.txt', subdir);

  assert_not_equals(await handle1.serialize(), await handle2.serialize());
}, 'serialization of two files of the same name in different directories returns different hashes');

directory_test(async (t, root_dir) => {
  const handle1 = await createEmptyFile(t, 'mtime.txt', root_dir);
  const handle2 = await createDirectory(t, 'subdir-name', root_dir);

  assert_not_equals(await handle1.serialize(), await handle2.serialize());
}, 'serialization of a file and a directory returns different hashes');

directory_test(async (t, root_dir) => {
  const handle1 = await createEmptyFile(t, 'mtime.txt', root_dir);
  const handle2 = await createDirectory(t, 'subdir-name', root_dir);

  assert_not_equals(await handle1.serialize(), await handle2.serialize());
}, 'serialization of a file and a directory of the same name returns different hashes');
