/**
 * Copyright (c) 2026 YCSB contributors. All rights reserved.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

package site.ycsb.db;

import org.codehaus.jackson.map.ObjectMapper;
import site.ycsb.ByteIterator;
import site.ycsb.DB;
import site.ycsb.DBException;
import site.ycsb.Status;
import site.ycsb.StringByteIterator;

import java.io.IOException;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.Vector;

/** Adapts YCSB operations to the coordinator's HTTP API. */
public class CoordenadorClient extends DB {
  private static final ObjectMapper JSON = new ObjectMapper();
  private String baseUrl;
  private String clientId;
  private int timeout;

  @Override
  public void init() throws DBException {
    baseUrl = getProperties().getProperty("coordenador.url", "http://127.0.0.1:5000");
    if (baseUrl.endsWith("/")) {
      baseUrl = baseUrl.substring(0, baseUrl.length() - 1);
    }
    clientId = "ycsb-" + UUID.randomUUID();
    try {
      timeout = Integer.parseInt(getProperties().getProperty("coordenador.timeout.ms", "5000"));
      if (timeout <= 0) {
        throw new NumberFormatException("timeout must be positive");
      }
    } catch (NumberFormatException e) {
      throw new DBException("Invalid coordenador.timeout.ms", e);
    }
  }

  private HttpURLConnection connect(String path, String method) throws IOException {
    HttpURLConnection conn = (HttpURLConnection) new URL(baseUrl + path).openConnection();
    conn.setRequestMethod(method);
    conn.setConnectTimeout(timeout);
    conn.setReadTimeout(timeout);
    conn.setRequestProperty("X-Client-ID", clientId);
    return conn;
  }

  private static Status status(int code) {
    if (code == 200) {
      return Status.OK;
    }
    if (code == 404) {
      return Status.NOT_FOUND;
    }
    if (code == 503) {
      return Status.SERVICE_UNAVAILABLE;
    }
    return Status.ERROR;
  }

  private static String recordKey(String table, String key) {
    return table + ":" + key;
  }

  @Override
  @SuppressWarnings("unchecked")
  public Status read(String table, String key, Set<String> fields,
      Map<String, ByteIterator> result) {
    HttpURLConnection conn = null;
    try {
      String encoded = URLEncoder.encode(recordKey(table, key), "UTF-8");
      conn = connect("/read?chave=" + encoded, "GET");
      int code = conn.getResponseCode();
      if (code != 200) {
        return status(code);
      }
      Map<String, Object> response = JSON.readValue(conn.getInputStream(), Map.class);
      Object value = response.get("valor");
      if (!(value instanceof Map)) {
        return Status.ERROR;
      }
      Map<String, Object> stored = (Map<String, Object>) value;
      for (Map.Entry<String, Object> entry : stored.entrySet()) {
        if (fields == null || fields.contains(entry.getKey())) {
          result.put(entry.getKey(), new StringByteIterator(String.valueOf(entry.getValue())));
        }
      }
      return Status.OK;
    } catch (IOException | ClassCastException e) {
      return Status.ERROR;
    } finally {
      if (conn != null) {
        conn.disconnect();
      }
    }
  }

  private Status write(String table, String key, Map<String, ByteIterator> values) {
    HttpURLConnection conn = null;
    try {
      Map<String, Object> body = new LinkedHashMap<>();
      body.put("chave", recordKey(table, key));
      Map<String, String> fields = new HashMap<>();
      for (Map.Entry<String, ByteIterator> entry : values.entrySet()) {
        fields.put(entry.getKey(), entry.getValue().toString());
      }
      body.put("valor", fields);
      byte[] payload = JSON.writeValueAsBytes(body);
      conn = connect("/write", "POST");
      conn.setRequestProperty("Content-Type", "application/json; charset=UTF-8");
      conn.setDoOutput(true);
      conn.setFixedLengthStreamingMode(payload.length);
      try (OutputStream out = conn.getOutputStream()) {
        out.write(payload);
      }
      return status(conn.getResponseCode());
    } catch (IOException e) {
      return Status.ERROR;
    } finally {
      if (conn != null) {
        conn.disconnect();
      }
    }
  }

  @Override
  public Status insert(String table, String key, Map<String, ByteIterator> values) {
    return write(table, key, values);
  }

  @Override
  public Status update(String table, String key, Map<String, ByteIterator> values) {
    return write(table, key, values);
  }

  @Override
  public Status scan(String table, String startkey, int recordcount,
      Set<String> fields, Vector<HashMap<String, ByteIterator>> result) {
    return Status.NOT_IMPLEMENTED;
  }

  @Override
  public Status delete(String table, String key) {
    return Status.NOT_IMPLEMENTED;
  }
}
