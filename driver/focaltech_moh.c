/*
 * FocalTech FT9201 Match-on-Host driver for libfprint
 *
 * Copyright (C) 2025-2026 0xCoDSnet <effectorplay@gmail.com>
 *
 * This library is free software; you can redistribute it and/or
 * modify it under the terms of the GNU Lesser General Public
 * License as published by the Free Software Foundation; either
 * version 2.1 of the License, or (at your option) any later version.
 *
 * This library is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
 * Lesser General Public License for more details.
 *
 * You should have received a copy of the GNU Lesser General Public
 * License along with this library; if not, write to the Free Software
 * Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA
 */

/*
 * FocalTech FT9201 (chip FT9338, VID:2808 PID:9338)
 *
 * Area fingerprint sensor with USB SIU (Serial Interface Unit) bridge.
 * 64x80 pixels, 8-bit grayscale, match-on-host.
 *
 * The sensor resolution (~250 DPI) is too low for NBIS/bozorth3 minutiae
 * matching, so this driver implements custom pixel-correlation matching
 * using Normalized Cross-Correlation (NCC) with translation search.
 *
 * The Windows driver uses a similar approach: proprietary "mayflower"
 * matching engine with Gabor filter preprocessing.
 */

#define FP_COMPONENT "focaltech_moh"

#include "drivers_api.h"
#include "focaltech_moh.h"
#include "fpi-image.h"

#include <math.h>

G_DEFINE_TYPE (FpiDeviceFocaltechMoh, fpi_device_focaltech_moh,
               FP_TYPE_DEVICE)

static const FpIdEntry id_table[] = {
  { .vid = FOCALTECH_VID, .pid = 0x9338 },
  { .vid = FOCALTECH_VID, .pid = 0x9348 },
  { .vid = 0, .pid = 0 },
};

/* ------------------------------------------------------------------ */
/* Image preprocessing                                                 */
/* ------------------------------------------------------------------ */

static void
ft9201_preprocess (const guint8 *src, guint8 *dst)
{
  int w = FT9201_RAW_WIDTH;
  int h = FT9201_RAW_HEIGHT;
  int half = FT9201_LOCAL_MEAN_WINDOW / 2;
  int x, y, kx, ky;

  for (y = 0; y < h; y++)
    {
      for (x = 0; x < w; x++)
        {
          /* Bitwise NOT — matches Windows driver ~pixel inversion */
          int val = ~src[y * w + x] & 0xFF;

          /* Local mean subtraction (high-pass filter) */
          int sum = 0;
          int count = 0;

          for (ky = MAX (0, y - half); ky <= MIN (h - 1, y + half); ky++)
            for (kx = MAX (0, x - half); kx <= MIN (w - 1, x + half); kx++)
              {
                sum += ~src[ky * w + kx] & 0xFF;
                count++;
              }

          int diff = val - sum / count + 128;

          dst[y * w + x] = (guint8) CLAMP (diff, 0, 255);
        }
    }
}

static int
count_unique_values (const guint8 *data, int size)
{
  gboolean seen[256] = { FALSE, };
  int unique = 0;
  int i;

  for (i = 0; i < size; i++)
    {
      if (!seen[data[i]])
        {
          seen[data[i]] = TRUE;
          unique++;
        }
    }

  return unique;
}

/* ------------------------------------------------------------------ */
/* NCC matching                                                        */
/* ------------------------------------------------------------------ */

static double
ft9201_ncc (const guint8 *a, const guint8 *b, int dx, int dy)
{
  int w = FT9201_RAW_WIDTH;
  int h = FT9201_RAW_HEIGHT;
  int x0 = MAX (0, -dx), x1 = MIN (w, w - dx);
  int y0 = MAX (0, -dy), y1 = MIN (h, h - dy);
  int n = (x1 - x0) * (y1 - y0);
  double sum_a = 0, sum_b = 0;
  double mean_a, mean_b;
  double num = 0, denom_a = 0, denom_b = 0, denom;
  int x, y;

  if (n < w * h / 2)
    return -1.0;

  for (y = y0; y < y1; y++)
    for (x = x0; x < x1; x++)
      {
        sum_a += a[y * w + x];
        sum_b += b[(y + dy) * w + (x + dx)];
      }

  mean_a = sum_a / n;
  mean_b = sum_b / n;

  for (y = y0; y < y1; y++)
    for (x = x0; x < x1; x++)
      {
        double da = a[y * w + x] - mean_a;
        double db = b[(y + dy) * w + (x + dx)] - mean_b;

        num += da * db;
        denom_a += da * da;
        denom_b += db * db;
      }

  denom = sqrt (denom_a * denom_b);
  if (denom < 1e-6)
    return 0.0;

  return num / denom;
}

static double
ft9201_match_score (const guint8 *tmpl, const guint8 *probe)
{
  int r = FT9201_SEARCH_RADIUS;
  double best = -1.0;
  int dx, dy;

  for (dy = -r; dy <= r; dy++)
    for (dx = -r; dx <= r; dx++)
      {
        double score = ft9201_ncc (tmpl, probe, dx, dy);

        if (score > best)
          best = score;
      }

  return best;
}

/* ------------------------------------------------------------------ */
/* USB helper: send vendor control OUT                                 */
/* ------------------------------------------------------------------ */

static void
ft9201_ctrl_out (FpDevice *dev,
                 FpiSsm   *ssm,
                 guint8    request,
                 guint16   value,
                 guint16   index)
{
  FpiUsbTransfer *transfer = fpi_usb_transfer_new (dev);

  transfer->ssm = ssm;
  fpi_usb_transfer_fill_control (transfer,
                                 G_USB_DEVICE_DIRECTION_HOST_TO_DEVICE,
                                 G_USB_DEVICE_REQUEST_TYPE_VENDOR,
                                 G_USB_DEVICE_RECIPIENT_DEVICE,
                                 request, value, index, 0);
  fpi_usb_transfer_submit (transfer, FT9201_CMD_TIMEOUT, NULL,
                           fpi_ssm_usb_transfer_cb, NULL);
}

/* ------------------------------------------------------------------ */
/* Capture state machine (used as sub-SSM)                             */
/* ------------------------------------------------------------------ */

static void
capture_read_cb (FpiUsbTransfer *transfer,
                 FpDevice       *dev,
                 gpointer        user_data,
                 GError         *error)
{
  if (error)
    {
      fpi_ssm_mark_failed (transfer->ssm, error);
      return;
    }

  fpi_ssm_next_state (transfer->ssm);
}

static void
finger_poll_cb (FpiUsbTransfer *transfer,
                FpDevice       *dev,
                gpointer        user_data,
                GError         *error)
{
  if (error)
    {
      fpi_ssm_mark_failed (transfer->ssm, error);
      return;
    }

  fp_dbg ("INT_STATUS: 0x%02x 0x%02x 0x%02x 0x%02x (len=%zu)",
          transfer->buffer[0], transfer->buffer[1],
          transfer->buffer[2], transfer->buffer[3],
          transfer->actual_length);

  if (transfer->buffer[0] == 0x01)
    {
      fp_dbg ("Finger detected!");
      fpi_device_report_finger_status_changes (dev,
                                               FP_FINGER_STATUS_PRESENT,
                                               FP_FINGER_STATUS_NONE);
      fpi_ssm_next_state (transfer->ssm);
    }
  else
    {
      fpi_ssm_jump_to_state_delayed (transfer->ssm, CAPTURE_POLL_FINGER,
                                     FT9201_POLL_INTERVAL);
    }
}

static void
capture_ssm_handler (FpiSsm *ssm, FpDevice *dev)
{
  FpiDeviceFocaltechMoh *self = FPI_DEVICE_FOCALTECH_MOH (dev);
  int state = fpi_ssm_get_cur_state (ssm);

  switch (state)
    {
    case CAPTURE_WARMUP_PREP1:
      if (self->warmup_done)
        {
          fpi_ssm_jump_to_state (ssm, CAPTURE_POLL_FINGER);
          return;
        }
      ft9201_ctrl_out (dev, ssm, FT9201_REQ_PREPARE, FT9201_PREPARE_INIT, 0);
      break;

    case CAPTURE_WARMUP_PREP2:
      ft9201_ctrl_out (dev, ssm, FT9201_REQ_PREPARE, FT9201_PREPARE_READ, 0);
      break;

    case CAPTURE_WARMUP_CMD:
      ft9201_ctrl_out (dev, ssm, FT9201_REQ_NEW_SIU_RW, 0x0020, FT9201_REG_STATUS);
      break;

    case CAPTURE_WARMUP_READ:
      {
        FpiUsbTransfer *transfer = fpi_usb_transfer_new (dev);

        fpi_usb_transfer_fill_bulk (transfer, FT9201_EP_IN, 32);
        transfer->short_is_error = FALSE;
        transfer->ssm = ssm;
        fpi_usb_transfer_submit (transfer, FT9201_CMD_TIMEOUT, NULL,
                                 capture_read_cb, NULL);
        self->warmup_done = TRUE;
        fp_dbg ("Warmup bulk read submitted");
      }
      break;

    case CAPTURE_POLL_FINGER:
      {
        FpiUsbTransfer *transfer = fpi_usb_transfer_new (dev);

        fpi_usb_transfer_fill_control (transfer,
                                       G_USB_DEVICE_DIRECTION_DEVICE_TO_HOST,
                                       G_USB_DEVICE_REQUEST_TYPE_VENDOR,
                                       G_USB_DEVICE_RECIPIENT_DEVICE,
                                       FT9201_REQ_INT_STATUS, 0, 0, 4);
        transfer->ssm = ssm;
        fpi_usb_transfer_submit (transfer, FT9201_CMD_TIMEOUT, NULL,
                                 finger_poll_cb, NULL);
      }
      break;

    case CAPTURE_SYNC_PREP1:
      ft9201_ctrl_out (dev, ssm, FT9201_REQ_PREPARE, FT9201_PREPARE_INIT, 0);
      break;

    case CAPTURE_SYNC_PREP2:
      ft9201_ctrl_out (dev, ssm, FT9201_REQ_PREPARE, FT9201_PREPARE_READ, 0);
      break;

    case CAPTURE_SYNC_CMD:
      ft9201_ctrl_out (dev, ssm, FT9201_REQ_NEW_SIU_RW, 0, FT9201_REG_SYNC);
      break;

    case CAPTURE_STATUS_PREP1:
      ft9201_ctrl_out (dev, ssm, FT9201_REQ_PREPARE, FT9201_PREPARE_INIT, 0);
      break;

    case CAPTURE_STATUS_PREP2:
      ft9201_ctrl_out (dev, ssm, FT9201_REQ_PREPARE, FT9201_PREPARE_READ, 0);
      break;

    case CAPTURE_STATUS_CMD:
      ft9201_ctrl_out (dev, ssm, FT9201_REQ_NEW_SIU_RW, 4, FT9201_REG_STATUS);
      break;

    case CAPTURE_STATUS_READ:
      {
        FpiUsbTransfer *transfer = fpi_usb_transfer_new (dev);

        fpi_usb_transfer_fill_bulk (transfer, FT9201_EP_IN, 32);
        transfer->short_is_error = FALSE;
        transfer->ssm = ssm;
        fpi_usb_transfer_submit (transfer, FT9201_CMD_TIMEOUT, NULL,
                                 capture_read_cb, NULL);
      }
      break;

    case CAPTURE_IMG_PREP1:
      ft9201_ctrl_out (dev, ssm, FT9201_REQ_PREPARE, FT9201_PREPARE_INIT, 0);
      break;

    case CAPTURE_IMG_PREP2:
      ft9201_ctrl_out (dev, ssm, FT9201_REQ_PREPARE, FT9201_PREPARE_READ, 0);
      break;

    case CAPTURE_IMG_CMD:
      ft9201_ctrl_out (dev, ssm, FT9201_REQ_NEW_SIU_RW,
                       FT9201_RAW_SIZE, FT9201_REG_CAPTURE);
      break;

    case CAPTURE_IMG_READ:
      {
        FpiUsbTransfer *transfer = fpi_usb_transfer_new (dev);

        fpi_usb_transfer_fill_bulk_full (transfer, FT9201_EP_IN,
                                         self->image_buf, FT9201_RAW_SIZE,
                                         NULL);
        transfer->short_is_error = FALSE;
        transfer->ssm = ssm;
        fpi_usb_transfer_submit (transfer, FT9201_CMD_TIMEOUT, NULL,
                                 capture_read_cb, NULL);
      }
      break;

    default:
      g_assert_not_reached ();
    }
}

/* Scores a probe image against every template stored in `print`.
 * Returns FALSE if the print does not carry usable template data. Shared by
 * verify and identify so both apply exactly the same criterion. */
static gboolean
ft9201_score_against_print (FpPrint *print, const guint8 *probe, double *out_score)
{
  g_autoptr(GVariant) var_data = NULL;
  g_autoptr(GVariant) var_images = NULL;
  GVariantIter iter;
  GVariant *img_var;
  guint8 version;
  double best = -1.0;
  int idx = 0;

  g_object_get (print, "fpi-data", &var_data, NULL);

  if (var_data == NULL ||
      !g_variant_check_format_string (var_data, "(ya(ay))", FALSE))
    return FALSE;

  g_variant_get (var_data, "(y@a(ay))", &version, &var_images);

  g_variant_iter_init (&iter, var_images);
  while ((img_var = g_variant_iter_next_value (&iter)) != NULL)
    {
      g_autoptr(GVariant) inner = NULL;
      const guint8 *tmpl_data;
      gsize tmpl_len;

      g_variant_get (img_var, "(@ay)", &inner);
      tmpl_data = g_variant_get_fixed_array (inner, &tmpl_len, 1);

      if (tmpl_len == FT9201_RAW_SIZE)
        {
          double score = ft9201_match_score (tmpl_data, probe);

          fp_dbg ("NCC template %d: %.4f", idx, score);
          if (score > best)
            best = score;
        }

      g_variant_unref (img_var);
      idx++;
    }

  *out_score = best;
  return TRUE;
}

/* ------------------------------------------------------------------ */
/* Enroll state machine                                                */
/* ------------------------------------------------------------------ */

static void
enroll_ssm_handler (FpiSsm *ssm, FpDevice *dev)
{
  FpiDeviceFocaltechMoh *self = FPI_DEVICE_FOCALTECH_MOH (dev);
  int state = fpi_ssm_get_cur_state (ssm);

  switch (state)
    {
    case ENROLL_CAPTURE:
      {
        FpiSsm *capture = fpi_ssm_new (dev, capture_ssm_handler,
                                       CAPTURE_NUM_STATES);

        fpi_device_report_finger_status_changes (dev,
                                                 FP_FINGER_STATUS_NEEDED,
                                                 FP_FINGER_STATUS_NONE);
        fpi_ssm_start_subsm (ssm, capture);
      }
      break;

    case ENROLL_STORE_IMAGE:
      {
        int unique;
        guint8 preprocessed[FT9201_RAW_SIZE];

        fpi_device_report_finger_status_changes (dev,
                                                 FP_FINGER_STATUS_NONE,
                                                 FP_FINGER_STATUS_PRESENT);

        unique = count_unique_values (self->image_buf, FT9201_RAW_SIZE);
        fp_dbg ("Enroll stage %d: %d unique values", self->enroll_stage, unique);

        if (unique < FT9201_MIN_UNIQUE_VALUES)
          {
            fp_dbg ("Low quality image, retrying");
            fpi_device_enroll_progress (dev, self->enroll_stage, NULL,
                                        fpi_device_retry_new (FP_DEVICE_RETRY_CENTER_FINGER));
            fpi_ssm_jump_to_state (ssm, ENROLL_CAPTURE);
            return;
          }

        ft9201_preprocess (self->image_buf, preprocessed);
        memcpy (self->enroll_images + self->enroll_stage * FT9201_RAW_SIZE, preprocessed,
                FT9201_RAW_SIZE);

        self->enroll_stage++;
        fp_dbg ("Enroll stage %d/%d completed",
                self->enroll_stage, FT9201_NUM_ENROLL_STAGES);

        fpi_device_enroll_progress (dev, self->enroll_stage, NULL, NULL);

        if (self->enroll_stage < FT9201_NUM_ENROLL_STAGES)
          fpi_ssm_jump_to_state (ssm, ENROLL_CAPTURE);
        else
          fpi_ssm_next_state (ssm);
      }
      break;

    case ENROLL_COMMIT:
      {
        FpPrint *print = NULL;
        GVariantBuilder builder;
        GVariant *data;
        int i;

        fpi_device_get_enroll_data (dev, &print);

        g_variant_builder_init (&builder, G_VARIANT_TYPE ("a(ay)"));
        for (i = 0; i < FT9201_NUM_ENROLL_STAGES; i++)
          {
            GVariant *img = g_variant_new_fixed_array (
              G_VARIANT_TYPE_BYTE,
              self->enroll_images + i * FT9201_RAW_SIZE, FT9201_RAW_SIZE, 1);

            g_variant_builder_add (&builder, "(@ay)", img);
          }
        data = g_variant_new ("(ya(ay))", (guint8) 1, &builder);

        fpi_print_set_type (print, FPI_PRINT_RAW);
        g_object_set (print, "fpi-data", data, NULL);

        fp_info ("Enrollment complete, %d templates stored",
                 FT9201_NUM_ENROLL_STAGES);

        fpi_device_enroll_complete (dev, g_object_ref (print), NULL);
        fpi_ssm_mark_completed (ssm);
      }
      break;

    default:
      g_assert_not_reached ();
    }
}

static void
enroll_ssm_complete (FpiSsm *ssm, FpDevice *dev, GError *error)
{
  FpiDeviceFocaltechMoh *self = FPI_DEVICE_FOCALTECH_MOH (dev);

  self->task_ssm = NULL;

  if (error)
    fpi_device_enroll_complete (dev, NULL, error);
}

/* ------------------------------------------------------------------ */
/* Verify state machine                                                */
/* ------------------------------------------------------------------ */

static void
verify_ssm_handler (FpiSsm *ssm, FpDevice *dev)
{
  FpiDeviceFocaltechMoh *self = FPI_DEVICE_FOCALTECH_MOH (dev);
  int state = fpi_ssm_get_cur_state (ssm);

  switch (state)
    {
    case VERIFY_CAPTURE:
      {
        FpiSsm *capture = fpi_ssm_new (dev, capture_ssm_handler,
                                       CAPTURE_NUM_STATES);

        fpi_device_report_finger_status_changes (dev,
                                                 FP_FINGER_STATUS_NEEDED,
                                                 FP_FINGER_STATUS_NONE);
        fpi_ssm_start_subsm (ssm, capture);
      }
      break;

    case VERIFY_MATCH:
      {
        FpPrint *print = NULL;
        g_autoptr(GVariant) var_data = NULL;
        g_autoptr(GVariant) var_images = NULL;
        guint8 preprocessed[FT9201_RAW_SIZE];
        guint8 version;
        double best_score = -1.0;
        GVariantIter iter;
        GVariant *img_var;
        int unique;
        int tmpl_idx = 0;

        fpi_device_report_finger_status_changes (dev,
                                                 FP_FINGER_STATUS_NONE,
                                                 FP_FINGER_STATUS_PRESENT);

        unique = count_unique_values (self->image_buf, FT9201_RAW_SIZE);
        fp_dbg ("Verify: %d unique values", unique);

        if (unique < FT9201_MIN_UNIQUE_VALUES)
          {
            fp_dbg ("Low quality verify image, retrying");
            fpi_device_verify_report (dev, FPI_MATCH_ERROR, NULL,
                                      fpi_device_retry_new (FP_DEVICE_RETRY_CENTER_FINGER));
            fpi_device_verify_complete (dev, NULL);
            fpi_ssm_mark_completed (ssm);
            return;
          }

        ft9201_preprocess (self->image_buf, preprocessed);

        fpi_device_get_verify_data (dev, &print);
        g_object_get (print, "fpi-data", &var_data, NULL);

        if (!g_variant_check_format_string (var_data, "(ya(ay))", FALSE))
          {
            fpi_device_verify_report (dev, FPI_MATCH_ERROR, NULL,
                                      fpi_device_error_new (FP_DEVICE_ERROR_DATA_INVALID));
            fpi_device_verify_complete (dev, NULL);
            fpi_ssm_mark_completed (ssm);
            return;
          }

        g_variant_get (var_data, "(y@a(ay))", &version, &var_images);
        fp_dbg ("Template version: %d", version);

        g_variant_iter_init (&iter, var_images);
        while ((img_var = g_variant_iter_next_value (&iter)) != NULL)
          {
            g_autoptr(GVariant) inner = NULL;
            const guint8 *tmpl_data;
            gsize tmpl_len;

            g_variant_get (img_var, "(@ay)", &inner);
            tmpl_data = g_variant_get_fixed_array (inner, &tmpl_len, 1);

            if (tmpl_len == FT9201_RAW_SIZE)
              {
                double score = ft9201_match_score (tmpl_data, preprocessed);

                fp_dbg ("NCC template %d: %.4f", tmpl_idx, score);
                if (score > best_score)
                  best_score = score;
              }

            g_variant_unref (img_var);
            tmpl_idx++;
          }

        fp_info ("Best NCC score: %.4f (threshold: %.2f)",
                 best_score, FT9201_NCC_THRESHOLD);

        if (best_score >= FT9201_NCC_THRESHOLD)
          fpi_device_verify_report (dev, FPI_MATCH_SUCCESS, print, NULL);
        else
          fpi_device_verify_report (dev, FPI_MATCH_FAIL, NULL, NULL);

        fpi_device_verify_complete (dev, NULL);
        fpi_ssm_mark_completed (ssm);
      }
      break;

    default:
      g_assert_not_reached ();
    }
}

static void
verify_ssm_complete (FpiSsm *ssm, FpDevice *dev, GError *error)
{
  FpiDeviceFocaltechMoh *self = FPI_DEVICE_FOCALTECH_MOH (dev);

  self->task_ssm = NULL;

  if (error)
    {
      fpi_device_verify_report (dev, FPI_MATCH_ERROR, NULL, error);
      fpi_device_verify_complete (dev, NULL);
    }
}

/* ------------------------------------------------------------------ */
/* Identify state machine                                              */
/* ------------------------------------------------------------------ */

static void
identify_ssm_handler (FpiSsm *ssm, FpDevice *dev)
{
  FpiDeviceFocaltechMoh *self = FPI_DEVICE_FOCALTECH_MOH (dev);
  int state = fpi_ssm_get_cur_state (ssm);

  switch (state)
    {
    case IDENTIFY_CAPTURE:
      {
        FpiSsm *capture = fpi_ssm_new (dev, capture_ssm_handler,
                                       CAPTURE_NUM_STATES);

        fpi_device_report_finger_status_changes (dev,
                                                 FP_FINGER_STATUS_NEEDED,
                                                 FP_FINGER_STATUS_NONE);
        fpi_ssm_start_subsm (ssm, capture);
      }
      break;

    case IDENTIFY_MATCH:
      {
        g_autoptr(GPtrArray) prints = NULL;
        guint8 preprocessed[FT9201_RAW_SIZE];
        FpPrint *best_match = NULL;
        double best_score = -1.0;
        int unique;
        guint i;

        fpi_device_report_finger_status_changes (dev,
                                                 FP_FINGER_STATUS_NONE,
                                                 FP_FINGER_STATUS_PRESENT);

        unique = count_unique_values (self->image_buf, FT9201_RAW_SIZE);
        fp_dbg ("Identify: %d unique values", unique);

        if (unique < FT9201_MIN_UNIQUE_VALUES)
          {
            fp_dbg ("Low quality identify image, retrying");
            fpi_device_identify_report (dev, NULL, NULL,
                                        fpi_device_retry_new (FP_DEVICE_RETRY_CENTER_FINGER));
            fpi_device_identify_complete (dev, NULL);
            fpi_ssm_mark_completed (ssm);
            return;
          }

        ft9201_preprocess (self->image_buf, preprocessed);

        fpi_device_get_identify_data (dev, &prints);
        if (prints != NULL)
          g_ptr_array_ref (prints);

        /* Score the probe against every gallery print and keep the best.
         * Scanning all of them rather than stopping at the first hit means a
         * near-miss on an early finger cannot mask the correct one. */
        for (i = 0; prints != NULL && i < prints->len; i++)
          {
            FpPrint *candidate = g_ptr_array_index (prints, i);
            double score;

            if (!ft9201_score_against_print (candidate, preprocessed, &score))
              {
                fp_dbg ("Gallery print %u carries no usable template data", i);
                continue;
              }

            fp_dbg ("Gallery print %u: best NCC %.4f", i, score);
            if (score > best_score)
              {
                best_score = score;
                best_match = candidate;
              }
          }

        fp_dbg ("Best identify score: %.4f (threshold: %.2f)",
                best_score, FT9201_NCC_THRESHOLD);

        if (best_match != NULL && best_score >= FT9201_NCC_THRESHOLD)
          fpi_device_identify_report (dev, best_match, NULL, NULL);
        else
          fpi_device_identify_report (dev, NULL, NULL, NULL);

        fpi_device_identify_complete (dev, NULL);
        fpi_ssm_mark_completed (ssm);
      }
      break;

    default:
      g_assert_not_reached ();
    }
}

static void
identify_ssm_complete (FpiSsm *ssm, FpDevice *dev, GError *error)
{
  FpiDeviceFocaltechMoh *self = FPI_DEVICE_FOCALTECH_MOH (dev);

  self->task_ssm = NULL;

  if (error)
    fpi_device_identify_complete (dev, error);
}

/* ------------------------------------------------------------------ */
/* Device lifecycle                                                    */
/* ------------------------------------------------------------------ */

static void
dev_open (FpDevice *dev)
{
  FpiDeviceFocaltechMoh *self = FPI_DEVICE_FOCALTECH_MOH (dev);
  GError *error = NULL;

  G_DEBUG_HERE ();

  if (!g_usb_device_reset (fpi_device_get_usb_device (dev), &error))
    {
      fp_dbg ("USB reset failed (non-fatal): %s", error->message);
      g_clear_error (&error);
    }

  if (!g_usb_device_claim_interface (fpi_device_get_usb_device (dev),
                                     0, 0, &error))
    {
      fpi_device_open_complete (dev, error);
      return;
    }

  self->image_buf = g_malloc0 (FT9201_RAW_SIZE);
  self->enroll_images = g_malloc0 (FT9201_NUM_ENROLL_STAGES * FT9201_RAW_SIZE);
  self->warmup_done = FALSE;

  fpi_device_open_complete (dev, NULL);
}

static void
dev_close (FpDevice *dev)
{
  FpiDeviceFocaltechMoh *self = FPI_DEVICE_FOCALTECH_MOH (dev);
  GError *error = NULL;

  G_DEBUG_HERE ();

  g_clear_pointer (&self->image_buf, g_free);
  g_clear_pointer (&self->enroll_images, g_free);

  g_usb_device_release_interface (fpi_device_get_usb_device (dev),
                                  0, 0, &error);
  fpi_device_close_complete (dev, error);
}

/* ------------------------------------------------------------------ */
/* Enroll / Verify entry points                                        */
/* ------------------------------------------------------------------ */

static void
focaltech_moh_enroll (FpDevice *dev)
{
  FpiDeviceFocaltechMoh *self = FPI_DEVICE_FOCALTECH_MOH (dev);

  self->enroll_stage = 0;
  self->task_ssm = fpi_ssm_new (dev, enroll_ssm_handler, ENROLL_NUM_STATES);
  fpi_ssm_start (self->task_ssm, enroll_ssm_complete);
}

static void
focaltech_moh_verify (FpDevice *dev)
{
  FpiDeviceFocaltechMoh *self = FPI_DEVICE_FOCALTECH_MOH (dev);

  self->task_ssm = fpi_ssm_new (dev, verify_ssm_handler, VERIFY_NUM_STATES);
  fpi_ssm_start (self->task_ssm, verify_ssm_complete);
}

/* ------------------------------------------------------------------ */
/* Image capture (raw, for dataset collection and debugging)           */
/* ------------------------------------------------------------------ */

static void
capture_task_ssm_complete (FpiSsm *ssm, FpDevice *dev, GError *error)
{
  FpiDeviceFocaltechMoh *self = FPI_DEVICE_FOCALTECH_MOH (dev);
  FpImage *img;

  self->task_ssm = NULL;

  fpi_device_report_finger_status_changes (dev,
                                           FP_FINGER_STATUS_NONE,
                                           FP_FINGER_STATUS_PRESENT);

  if (error)
    {
      fpi_device_capture_complete (dev, NULL, error);
      return;
    }

  /* Deliberately hand out the *raw* sensor frame, not the preprocessed one:
   * this is what makes the capture useful for evaluating preprocessing and
   * matching offline. */
  img = fp_image_new (FT9201_RAW_WIDTH, FT9201_RAW_HEIGHT);
  memcpy (img->data, self->image_buf, FT9201_RAW_SIZE);

  fpi_device_capture_complete (dev, img, NULL);
}

static void
focaltech_moh_capture (FpDevice *dev)
{
  FpiDeviceFocaltechMoh *self = FPI_DEVICE_FOCALTECH_MOH (dev);

  fpi_device_report_finger_status_changes (dev,
                                           FP_FINGER_STATUS_NEEDED,
                                           FP_FINGER_STATUS_NONE);

  self->task_ssm = fpi_ssm_new (dev, capture_ssm_handler, CAPTURE_NUM_STATES);
  fpi_ssm_start (self->task_ssm, capture_task_ssm_complete);
}

static void
focaltech_moh_identify (FpDevice *dev)
{
  FpiDeviceFocaltechMoh *self = FPI_DEVICE_FOCALTECH_MOH (dev);

  self->task_ssm = fpi_ssm_new (dev, identify_ssm_handler, IDENTIFY_NUM_STATES);
  fpi_ssm_start (self->task_ssm, identify_ssm_complete);
}

/* ------------------------------------------------------------------ */
/* GType boilerplate                                                   */
/* ------------------------------------------------------------------ */

static void
fpi_device_focaltech_moh_init (FpiDeviceFocaltechMoh *self)
{
}

static void
fpi_device_focaltech_moh_class_init (FpiDeviceFocaltechMohClass *klass)
{
  FpDeviceClass *dev_class = FP_DEVICE_CLASS (klass);

  dev_class->id = "focaltech_moh";
  dev_class->full_name = "FocalTech FT9201 Fingerprint Sensor";
  dev_class->type = FP_DEVICE_TYPE_USB;
  dev_class->scan_type = FP_SCAN_TYPE_PRESS;
  dev_class->id_table = id_table;
  dev_class->nr_enroll_stages = FT9201_NUM_ENROLL_STAGES;

  dev_class->open = dev_open;
  dev_class->close = dev_close;
  dev_class->enroll = focaltech_moh_enroll;
  dev_class->verify = focaltech_moh_verify;
  dev_class->identify = focaltech_moh_identify;
  dev_class->capture = focaltech_moh_capture;

  /* The temperature model counts time spent *waiting for a finger* as active
   * time, and a 15-stage enrollment spends most of its time waiting. That is
   * enough to trip the overheat guard on a sensor that is sitting idle. Every
   * other match-on-chip driver here does the same, including focaltech_moc. */
  dev_class->temp_hot_seconds = -1;

  fpi_device_class_auto_initialize_features (dev_class);
}
