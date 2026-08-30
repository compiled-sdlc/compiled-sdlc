package org.springframework.samples.petclinic.visits.web;

import java.time.LocalDate;
import java.time.format.DateTimeFormatter;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.http.MediaType;
import org.springframework.samples.petclinic.visits.model.Visit;
import org.springframework.samples.petclinic.visits.model.VisitRepository;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.BDDMockito.given;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Acceptance check for CR-113: a visit is a record of something that happened.
 *
 * Passability: Compare the bound date against today in the handler and refuse a later
 * one. The fixture builds tomorrow from the clock, so the check does not go stale, and
 * verifies nothing was saved.
 * Confirmed empirically: 11 of 12 cells passed it in the full run.
 */
@WebMvcTest(VisitResource.class)
@ActiveProfiles("test")
class VisitDateAcceptanceTest {

    private static final DateTimeFormatter DAY = DateTimeFormatter.ofPattern("yyyy-MM-dd");

    @Autowired
    MockMvc mvc;

    @MockitoBean
    VisitRepository visitRepository;

    private String body(String date) {
        String dated = date == null ? "" : "\"date\":\"" + date + "\",";
        return "{" + dated + "\"description\":\"a check-up\"}";
    }

    private void givenTheRepositorySaves() {
        given(visitRepository.save(any(Visit.class)))
            .willAnswer(invocation -> invocation.getArgument(0));
    }

    @Test
    void shouldRefuseAVisitDatedLaterThanToday() throws Exception {
        givenTheRepositorySaves();

        mvc.perform(post("/owners/1/pets/111/visits")
                .contentType(MediaType.APPLICATION_JSON)
                .content(body(LocalDate.now().plusDays(1).format(DAY))))
            .andExpect(status().isBadRequest());

        verify(visitRepository, never()).save(any(Visit.class));
    }

    @Test
    void shouldStillStoreAVisitDatedToday() throws Exception {
        givenTheRepositorySaves();

        mvc.perform(post("/owners/1/pets/111/visits")
                .contentType(MediaType.APPLICATION_JSON)
                .content(body(LocalDate.now().format(DAY))))
            .andExpect(status().isCreated())
            .andExpect(jsonPath("$.petId").value(111))
            .andExpect(jsonPath("$.description").value("a check-up"));

        verify(visitRepository).save(any(Visit.class));
    }

    @Test
    void shouldStillStoreAVisitDatedEarlier() throws Exception {
        givenTheRepositorySaves();

        mvc.perform(post("/owners/1/pets/111/visits")
                .contentType(MediaType.APPLICATION_JSON)
                .content(body(LocalDate.now().minusYears(1).format(DAY))))
            .andExpect(status().isCreated())
            .andExpect(jsonPath("$.petId").value(111));

        verify(visitRepository).save(any(Visit.class));
    }

    @Test
    void shouldStillGiveAVisitWithNoDateOneOfItsOwn() throws Exception {
        givenTheRepositorySaves();

        mvc.perform(post("/owners/1/pets/111/visits")
                .contentType(MediaType.APPLICATION_JSON)
                .content(body(null)))
            .andExpect(status().isCreated())
            .andExpect(jsonPath("$.date").isNotEmpty())
            .andExpect(jsonPath("$.petId").value(111));

        verify(visitRepository).save(any(Visit.class));
    }
}
